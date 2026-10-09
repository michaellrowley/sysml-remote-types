import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from typelink import emit, fetch, kaitai, languages, parser, repository, spec, sysml  # noqa: E402
from typelink.__main__ import main  # noqa: E402

KAITAI_COMPILER = shutil.which("ksc") or shutil.which("kaitai-struct-compiler")

LINK = '''item def %s {
    @TypeLink {
        origin = TypeOrigin::%s;
        uri = "%s";
    }
}'''
GOOD = LINK % ("lell_packet", "C",
               "https://github.com/greatscottgadgets/libbtbb/blob/master/lib/src/bluetooth_le_packet.h")

C_SRC = '''
#include <stdint.h>
#define N (2+2)
typedef struct { uint8_t a; uint16_t b; } inner_t;
struct pkt { uint8_t pre; inner_t in[N]; char *p; double d; };
struct bits { uint8_t pre; int x:3; int y:6; };
union u { char c; long l[2]; };
struct bad { uint8_t pre; unknown_t u; };
'''
PROTO_SRC = '''syntax = "proto3";
message Inner { fixed32 id = 1; }
message Msg { int32 a = 1; repeated string tags = 2; Inner in = 3; }
'''
CPP_ROUND_TRIP_SRC = '''
struct Header {
    unsigned char kind;
    unsigned short length;
};
struct Packet {
    Header header;
    unsigned int sequence;
    unsigned char payload[4];
};
'''
CPP_KAITAI_ROUND_TRIPS = (
    (
        "nested structs, padding, and fixed arrays",
        CPP_ROUND_TRIP_SRC,
        None,
        {},
        (
            "  - id: header\n    type: packet__header",
            "  - id: sequence\n    type: u4",
            "repeat-expr: 4",
        ),
    ),
    (
        "scalar widths and aliases",
        '''typedef unsigned short Word;
enum State { Off, On };
struct Packet {
    signed char delta;
    unsigned char flags;
    Word length;
    State state;
    long long signed_wide;
    unsigned long long unsigned_wide;
    float ratio;
    double measure;
    bool ready;
};''',
        None,
        {},
        ("type: s1", "type: u1", "type: u2", "type: s4", "type: s8",
         "type: u8", "type: f4", "type: f8", "  - id: ready\n    type: u1"),
    ),
    (
        "signed bitfields",
        '''struct Packet {
    unsigned char prefix;
    signed int delta : 3;
    unsigned int mode : 5;
};''',
        None,
        {},
        ("type: b3", "type: b5", 'value: "delta >= 4 ? delta - 8 : delta"'),
    ),
    (
        "opaque union storage",
        '''union Payload {
    unsigned int number;
    unsigned char bytes[4];
};
struct Packet {
    unsigned char tag;
    Payload payload;
};''',
        None,
        {},
        ("type: packet__payload", "- id: data\n        size: 4"),
    ),
    (
        "pointer size under ILP32",
        '''struct Packet {
    unsigned char tag;
    void *address;
};''',
        "ilp32",
        {},
        ("  - id: address\n    type: u4",),
    ),
    (
        "multidimensional arrays",
        '''struct Packet {
    unsigned short grid[2][3];
};''',
        None,
        {},
        ("  - id: grid\n    type: u2", "repeat-expr: 6"),
    ),
    (
        "configured byte and bit endianness",
        '''struct Packet {
    unsigned int first : 3;
    unsigned int second : 5;
};''',
        None,
        {"endian": "be", "bit_endian": "be"},
        ("  endian: be", "  bit-endian: be"),
    ),
    (
        "default signedness for plain char",
        "struct Packet { char value; };",
        None,
        {},
        ("  - id: value\n    type: u1",),
    ),
    (
        "signedness override for plain char",
        "struct Packet { char value; };",
        None,
        {"integer_signedness": "signed"},
        ("  - id: value\n    type: s1",),
    ),
    (
        "C++ class layout",
        '''class Packet {
public:
    unsigned short value;
};''',
        None,
        {},
        ("  - id: value\n    type: u2",),
    ),
)


def expand_with(origin, element, source, **kw):
    return emit.expand(LINK % (element, origin, "file:///x"), fetcher=lambda uri: source, **kw)


class SpecTests(unittest.TestCase):
    def test_spec(self):
        s = spec.load()
        self.assertEqual(s.origins, ["C", "CPP", "Protobuf"])
        self.assertEqual(s.link_attrs, {"origin": "TypeOrigin", "uri": "String"})
        self.assertEqual(s.metadata["DataSize"], {"bits": "Natural"})
        self.assertEqual(s.metadata["DataOffset"], {"bits": "Natural"})
        self.assertEqual(s.metadata["DataEncoding"]["field_number"], "Natural")

    def test_every_origin_has_importer(self):
        self.assertEqual(sorted(spec.load().origins), languages.origins())

    def test_rfc_in_sync(self):
        self.assertTrue(spec.sync_rfc(write=False))


class ParseTests(unittest.TestCase):
    def test_good(self):
        (l,) = parser.parse(GOOD)
        self.assertEqual((l.element, l.origin), ("lell_packet", "C"))

    def test_regex_proof(self):
        # annotation text inside a comment/string must not count
        text = '/* @TypeLink { origin = TypeOrigin::C; } */ item def x;'
        self.assertEqual(parser.parse(text), [])

    def test_bad(self):
        for bad in (GOOD.replace("::C", "::Rust"), GOOD.replace("origin", "orig"),
                    GOOD.replace('"https://', '"'), "item def x { @TypeLink { } }"):
            with self.assertRaises(parser.TypeLinkError):
                parser.parse(bad)

    def test_syntax_error(self):
        with self.assertRaises(sysml.SysMLSyntaxError):
            parser.parse("item def {{{")


class FetchTests(unittest.TestCase):
    def test_github_blob_urls_rewrite_to_raw_content(self):
        self.assertEqual(
            fetch.raw_url("https://github.com/org/repo/blob/feature/v2/src/file.h"),
            "https://raw.githubusercontent.com/org/repo/feature/v2/src/file.h")

    def test_non_blob_urls_are_not_rewritten(self):
        for uri in (
            "https://github.com/org/repo/tree/main/src",
            "https://example.com/org/repo/blob/main/file.h",
            "file:///tmp/file.h",
        ):
            with self.subTest(uri=uri):
                self.assertEqual(fetch.raw_url(uri), uri)

    def test_http_fetch_rewrites_url_and_decodes_bytes(self):
        with patch("typelink.fetch.urllib.request.urlopen",
                   return_value=nullcontext(BytesIO(b"source"))) as open_url:
            self.assertEqual(
                fetch.fetch("https://github.com/org/repo/blob/main/file.h"), "source")
        open_url.assert_called_once_with(
            "https://raw.githubusercontent.com/org/repo/main/file.h", timeout=30)

    def test_http_fetch_enforces_max_bytes(self):
        with patch("typelink.fetch.urllib.request.urlopen",
                   return_value=nullcontext(BytesIO(b"four"))):
            with self.assertRaisesRegex(ValueError, "exceeds 3 bytes"):
                fetch.fetch("https://example.com/file.h", max_bytes=3)


class ExpandTests(unittest.TestCase):
    def test_c(self):
        out = expand_with("C", "pkt", C_SRC)
        self.assertIn("@DataSize { bits = 320; }", out)
        self.assertIn("@DataLayout { kind = DataLayoutKind::Struct; }", out)
        self.assertIn("@DataOffset { bits = 16; }", out)
        self.assertIn("@DataSigned { value = false; }", out)
        self.assertEqual(out.count("@DataSigned { value = false; }"), 4)
        self.assertIn("item 'in' : inner_t[4] {", out)
        self.assertIn("@DataSize { bits = 32; }", out)
        self.assertIn("item def inner_t", out)
        self.assertIn("attribute p : ScalarValues::Integer {", out)
        self.assertIn("@DataSize { bits = 64; }", out)

    def test_c_additional_source_resolves_aggregate(self):
        out = expand_with(
            "C", "packet", "struct packet { struct header hdr; };",
            additional_sources=["struct header { int kind; };"])
        self.assertIn("item def header", out)
        self.assertIn("item hdr : header", out)
        self.assertIn("attribute kind : ScalarValues::Integer", out)
        self.assertNotIn("ref item hdr", out)

    def test_cpp_additional_source_resolves_class(self):
        out = expand_with(
            "CPP", "Packet", "class Packet { public: Header hdr; };",
            additional_sources=["class Header { public: int kind; };"])
        self.assertIn("item def Header", out)
        self.assertIn("item hdr : Header", out)
        self.assertIn("attribute kind : ScalarValues::Integer", out)
        self.assertNotIn("ref item hdr", out)

    def test_data_model(self):
        out = expand_with("C", "u", C_SRC, data_model="ilp32")
        self.assertIn("@DataSize { bits = 64; }", out)
        out = expand_with("C", "u", C_SRC, data_model="lp64")
        self.assertIn("@DataSize { bits = 128; }", out)

    def test_bitfields(self):
        out = expand_with("C", "bits", C_SRC)
        self.assertIn("attribute x : ScalarValues::Integer {", out)
        self.assertIn("@DataSize { bits = 3; }", out)
        self.assertIn("@DataSize { bits = 64; }", out)
        self.assertIn("@DataOffset { bits = 32; }", out)
        self.assertIn("@DataOffset { bits = 35; }", out)

    def test_union_layout_metadata(self):
        out = expand_with("C", "u", C_SRC)
        self.assertIn("@DataLayout { kind = DataLayoutKind::Union; }", out)
        self.assertEqual(out.count("@DataOffset { bits = 0; }"), 2)

    def test_unresolved_has_no_total(self):
        warnings = []
        out = expand_with("C", "bad", C_SRC, warn=warnings.append)
        self.assertIn("ref item u : unknown_t;", out)
        self.assertEqual(len(warnings), 1)
        self.assertNotIn("@DataSize { bits = 8; }\n    attribute", out.split("typelink:begin")[1][:60])

    def test_protobuf(self):
        out = expand_with("Protobuf", "Msg", PROTO_SRC)
        self.assertIn("@DataLayout { kind = DataLayoutKind::Protobuf; }", out)
        self.assertIn(
            "@DataEncoding { field_number = 1; kind = DataEncodingKind::Varint; "
            'wire_type = 0; source_type = "int32"; packed = false; }', out)
        self.assertIn("attribute tags : ScalarValues::String[0..*] {", out)
        self.assertIn("item def Inner", out)

    def test_protobuf_preserves_wire_kinds_and_map_types(self):
        source = '''syntax = "proto3";
message Child { fixed32 id = 1; }
message Packet {
    sint32 delta = 1;
    repeated int32 values = 2;
    Child child = 3;
    map<string, int64> counts = 4;
}'''
        out = expand_with("Protobuf", "Packet", source)
        self.assertIn(
            "@DataEncoding { field_number = 1; kind = DataEncodingKind::Zigzag; "
            'wire_type = 0; source_type = "sint32"; packed = false; }', out)
        self.assertIn(
            "@DataEncoding { field_number = 2; kind = DataEncodingKind::Varint; "
            'wire_type = 2; source_type = "int32"; packed = true; }', out)
        self.assertIn(
            "@DataEncoding { field_number = 4; kind = DataEncodingKind::Map; "
            'wire_type = 2; source_type = "map"; packed = false; }', out)
        self.assertIn(
            '@DataMap { key_type = "string"; value_type = "int64"; '
            'value_kind = "scalar"; }', out)

    def test_protobuf_additional_source_resolves_message(self):
        out = expand_with(
            "Protobuf", "Msg",
            "message Msg { optional Other child = 1; repeated Other children = 2; }",
            additional_sources=["message Other { int32 value = 1; }"])
        self.assertIn("item def Other", out)
        self.assertIn("item child : Other[0..1]", out)
        self.assertIn("item children : Other[0..*]", out)
        self.assertNotIn("ref item child", out)

    def test_idempotent(self):
        once = expand_with("C", "pkt", C_SRC)
        twice = emit.expand(once, fetcher=lambda uri: C_SRC)
        self.assertEqual(once, twice)

    def test_file_uri_and_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "packet.h"
            source.write_text(C_SRC)
            uri = source.as_uri()
            out = emit.expand(LINK % ("pkt", "C", uri))
            self.assertIn("bits = 320", out)
            with self.assertRaises(ValueError):
                expand_with("C", "nope", C_SRC)
            with self.assertRaises(ValueError):
                emit.expand(LINK % ("pkt", "C", uri), max_bytes=10)

    def test_keyword_member_quoted(self):
        out = expand_with("C", "k", "struct k { int part; };")
        self.assertIn("attribute 'part'", out)


class KaitaiTests(unittest.TestCase):
    def cpp_round_trip(self, source=CPP_ROUND_TRIP_SRC, data_model=None, **options):
        expanded = expand_with("CPP", "Packet", source, data_model=data_model)
        sysml.parse(expanded)
        return expanded, kaitai.generate(expanded, item="Packet", **options)

    def test_cpp_source_round_trips_through_sysml_to_kaitai(self):
        expanded, schema = self.cpp_round_trip()

        self.assertIn("item def Header", expanded)
        self.assertIn("item header : Header", expanded)
        self.assertIn("@DataOffset { bits = 32; }", expanded)
        self.assertIn("  id: packet", schema)
        self.assertIn("  - id: header\n    type: packet__header", schema)
        self.assertIn("  - id: sequence\n    type: u4", schema)
        self.assertIn(
            "  - id: payload\n    type: u1\n    repeat: expr\n    repeat-expr: 4",
            schema)

    @unittest.skipUnless(KAITAI_COMPILER,
                         "Kaitai Struct compiler (ksc) is not installed")
    def test_cpp_round_trip_kaitai_schema_compiles(self):
        for name, source, data_model, options, _ in CPP_KAITAI_ROUND_TRIPS:
            with self.subTest(feature=name):
                _, schema = self.cpp_round_trip(source, data_model, **options)

                with tempfile.TemporaryDirectory() as temp:
                    schema_path = Path(temp) / "packet.ksy"
                    schema_path.write_text(schema)
                    result = subprocess.run(
                        [KAITAI_COMPILER, "-t", "python", "--outdir", temp,
                         str(schema_path)],
                        capture_output=True, text=True)

                self.assertEqual(
                    result.returncode, 0, result.stdout + result.stderr)

    def test_cpp_round_trips_cover_kaitai_features(self):
        for name, source, data_model, options, expected in CPP_KAITAI_ROUND_TRIPS:
            with self.subTest(feature=name):
                _, schema = self.cpp_round_trip(source, data_model, **options)

                for snippet in expected:
                    self.assertIn(snippet, schema)

    def test_checked_in_example_matches_generated_schema(self):
        root = Path(__file__).resolve().parents[2]
        model = (root / "examples" / "packet.sysml").read_text()
        expected = (root / "examples" / "packet.ksy").read_text()
        self.assertEqual(kaitai.generate(model, item="Packet"), expected)

    def test_native_item_is_a_packed_little_endian_sequence(self):
        model = '''item def Packet {
    attribute kind : ScalarValues::Integer { @DataSize { bits = 8; } }
    attribute count : ScalarValues::Integer[2] { @DataSize { bits = 16; } }
}'''
        out = kaitai.generate(model)
        self.assertIn("  id: packet", out)
        self.assertIn("  endian: le", out)
        self.assertIn("  - id: kind\n    type: u1", out)
        self.assertIn(
            "  - id: count\n    type: u2\n    repeat: expr\n    repeat-expr: 2",
            out)
        self.assertNotIn("padding_", out)

    def test_native_scalar_mapping_and_signedness(self):
        model = '''item def Values {
    attribute signed_value : ScalarValues::Integer {
        @DataSize { bits = 32; }
        @DataSigned { value = true; }
    }
    attribute ratio : ScalarValues::Real { @DataSize { bits = 32; } }
    attribute enabled : ScalarValues::Boolean { @DataSize { bits = 8; } }
    attribute label : ScalarValues::String { @DataSize { bits = 24; } }
}'''
        out = kaitai.generate(model)
        self.assertIn("type: s4", out)
        self.assertIn("type: f4", out)
        self.assertIn("type: u1", out)
        self.assertIn("type: str\n    size: 3", out)

    def test_imported_struct_layout_generates_padding(self):
        imported_model = '''item def Packet {
    @DataLayout { kind = DataLayoutKind::Struct; }
    @DataSize { bits = 64; }
    attribute tag : ScalarValues::Integer {
        @DataSize { bits = 8; }
        @DataOffset { bits = 0; }
        @DataSigned { value = false; }
    }
    attribute length : ScalarValues::Integer {
        @DataSize { bits = 32; }
        @DataOffset { bits = 32; }
        @DataSigned { value = false; }
    }
}'''
        out = kaitai.generate(imported_model)
        self.assertIn("  - id: tag\n    type: u1", out)
        self.assertIn("  - id: padding_0\n    size: 3", out)
        self.assertIn("  - id: length\n    type: u4", out)

    def test_union_is_preserved_as_opaque_bytes(self):
        imported_model = '''item def Sample {
    @DataLayout { kind = DataLayoutKind::Union; }
    @DataSize { bits = 32; }
    attribute a : ScalarValues::Integer {
        @DataSize { bits = 8; }
        @DataOffset { bits = 0; }
    }
    attribute b : ScalarValues::Integer {
        @DataSize { bits = 32; }
        @DataOffset { bits = 0; }
    }
}'''
        out = kaitai.generate(imported_model)
        self.assertIn("  - id: data\n    size: 4", out)
        self.assertNotIn("  - id: a", out)
        self.assertNotIn("  - id: b", out)

    def test_imported_bitfield_offsets_and_signed_values_are_preserved(self):
        imported_model = '''item def Bits {
    @DataLayout { kind = DataLayoutKind::Struct; }
    @DataSize { bits = 64; }
    attribute prefix : ScalarValues::Integer {
        @DataSize { bits = 8; }
        @DataOffset { bits = 0; }
    }
    attribute x : ScalarValues::Integer {
        @DataSize { bits = 3; }
        @DataOffset { bits = 32; }
        @DataSigned { value = true; }
    }
    attribute y : ScalarValues::Integer {
        @DataSize { bits = 6; }
        @DataOffset { bits = 35; }
        @DataSigned { value = true; }
    }
}'''
        out = kaitai.generate(imported_model)
        self.assertIn("  - id: padding_0\n    size: 3", out)
        self.assertIn("  - id: x\n    type: b3", out)
        self.assertIn("  - id: y\n    type: b6", out)
        self.assertIn('value: "x >= 4 ? x - 8 : x"', out)
        self.assertIn('value: "y >= 32 ? y - 64 : y"', out)

    def test_protobuf_wire_fields_and_nested_types(self):
        source = '''syntax = "proto3";
message Child { fixed32 id = 1; }
message Packet {
    int32 id = 1;
    repeated sint32 values = 2;
    string name = 3;
    Child child = 4;
    map<string, int32> counts = 5;
}'''
        expanded = expand_with("Protobuf", "Packet", source)
        out = kaitai.generate(expanded, item="Packet")
        self.assertIn("type: pb_packet_field\n    repeat: eos", out)
        self.assertIn("8: pb_packet_id_value", out)
        self.assertIn("18: pb_packet_values_packed_packed", out)
        self.assertIn("26: pb_packet_name_value", out)
        self.assertIn("34: pb_packet_child_value", out)
        self.assertIn("42: pb_packet_counts_value", out)
        self.assertIn("type: packet__child", out)
        self.assertIn("10: pb_packet_counts_entry_key", out)
        self.assertIn("16: pb_packet_counts_entry_value", out)
        self.assertIn("protobuf_unknown(tag.value % 8)", out)

    def test_protobuf_enum_map_value_is_not_mistaken_for_message(self):
        source = '''syntax = "proto3";
enum Status { UNKNOWN = 0; READY = 1; }
message Packet { map<string, Status> states = 1; }'''
        expanded = expand_with("Protobuf", "Packet", source)
        self.assertIn('value_kind = "enum"', expanded)
        out = kaitai.generate(expanded)
        self.assertIn("16: pb_packet_states_entry_value", out)

    def test_unresolved_protobuf_field_is_not_assumed_to_be_a_group(self):
        expanded = expand_with("Protobuf", "Packet",
                               'syntax = "proto3"; message Packet { Missing item = 1; }')
        self.assertIn("DataEncodingKind::Unresolved", expanded)
        with self.assertRaisesRegex(kaitai.KaitaiError, "unresolved"):
            kaitai.generate(expanded)

    def test_protobuf_endian_is_fixed_by_wire_format(self):
        expanded = expand_with("Protobuf", "Msg", PROTO_SRC)
        with self.assertRaisesRegex(kaitai.KaitaiError, "always little-endian"):
            kaitai.generate(expanded, endian="be")

    def test_recursive_protobuf_message_uses_named_body_type(self):
        source = '''syntax = "proto3";
message Node {
    Node next = 1;
    int32 value = 2;
}'''
        expanded = expand_with("Protobuf", "Node", source)
        out = kaitai.generate(expanded)
        self.assertIn("  - id: message\n    type: node__body", out)
        self.assertIn("  node__body:\n    seq:", out)
        self.assertIn("type: node__body\n        size: length", out)

    def test_native_signed_bit_field_gets_signed_instance(self):
        model = '''item def Packed {
    attribute delta : ScalarValues::Integer {
        @DataSize { bits = 3; }
        @DataSigned { value = true; }
    }
}'''
        out = kaitai.generate(model)
        self.assertIn("type: b3", out)
        self.assertIn("delta_signed:", out)
        self.assertIn('value: "delta >= 4 ? delta - 8 : delta"', out)

    def test_selects_one_top_level_item(self):
        model = '''item def First { attribute value : ScalarValues::Integer { @DataSize { bits = 8; } } }
item def Second { attribute value : ScalarValues::Integer { @DataSize { bits = 8; } } }'''
        with self.assertRaisesRegex(kaitai.KaitaiError, "--item"):
            kaitai.generate(model)
        self.assertIn("id: second", kaitai.generate(model, item="Second"))


class RepositoryTests(unittest.TestCase):
    def test_clone_mode_is_opt_in(self):
        with patch("typelink.emit.repository.fetch_sources") as fetch_sources:
            expand_with("C", "k", "struct k { int value; };")
        fetch_sources.assert_not_called()

    def test_clone_mode_cannot_be_combined_with_custom_fetcher(self):
        link = LINK % ("k", "C", "https://github.com/example/fixture/blob/main/k.h")
        with self.assertRaisesRegex(ValueError, "fetcher and clone_repo"):
            emit.expand(link, fetcher=lambda uri: "", clone_repo=True)

    def test_expand_uses_cloned_sources_when_requested(self):
        link = LINK % (
            "packet", "C",
            "https://github.com/example/fixture/blob/main/packet.h")
        source = "struct packet { struct header hdr; };"
        with patch("typelink.emit.repository.fetch_sources",
                   return_value=(source, ["struct header { int kind; };"])):
            out = emit.expand(link, clone_repo=True)
        self.assertIn("item def header", out)
        self.assertIn("item hdr : header", out)

    def test_clone_mode_passes_max_bytes_to_repository_fetch(self):
        link = LINK % (
            "packet", "C",
            "https://github.com/example/fixture/blob/main/packet.h")
        with patch("typelink.emit.repository.fetch_sources",
                   return_value=("struct packet {};", [])) as fetch_sources:
            emit.expand(link, clone_repo=True, max_bytes=123)
        fetch_sources.assert_called_once_with(
            "https://github.com/example/fixture/blob/main/packet.h", "C", 123)

    def test_rejects_non_github_and_malformed_blob_urls_before_cloning(self):
        invalid_uris = (
            "http://github.com/example/fixture/blob/main/packet.h",
            "https://github.com.evil.test/example/fixture/blob/main/packet.h",
            "https://github.com/example/fixture/tree/main/packet.h",
            "https://github.com/example/fixture/blob/main",
            "https://github.com/../fixture/blob/main/packet.h",
            "https://github.com/example/fixture/blob/main/%2e%2e%2fsecret.h",
            "https://github.com/example/.git/blob/main/packet.h",
            "file:///tmp/packet.h",
        )
        with patch.object(repository, "_git") as git:
            for uri in invalid_uris:
                with self.subTest(uri=uri), self.assertRaises(ValueError):
                    repository.fetch_sources(uri, "C")
        git.assert_not_called()

    def test_rejects_unsupported_origin_before_cloning(self):
        with patch.object(repository, "_git") as git:
            with self.assertRaisesRegex(ValueError, "unsupported for origin Rust"):
                repository.fetch_sources(
                    "https://github.com/example/fixture/blob/main/packet.rs", "Rust")
        git.assert_not_called()

    def test_clones_github_ref_and_collects_peer_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            source_repo = Path(temp) / "source"
            source_repo.mkdir()
            subprocess.run(["git", "init", "-b", "main", str(source_repo)],
                           check=True, capture_output=True)
            subprocess.run(["git", "-C", str(source_repo), "config",
                            "user.name", "TypeLink Test"], check=True)
            subprocess.run(["git", "-C", str(source_repo), "config",
                            "user.email", "typelink@example.invalid"], check=True)
            (source_repo / "packet.h").write_text(
                "struct packet { struct header hdr; };")
            (source_repo / "header.h").write_text(
                "struct header { int kind; };")
            (source_repo / "service.proto").write_text(
                "message Service { Child child = 1; }")
            (source_repo / "child.proto").write_text(
                "message Child { string name = 1; }")
            (source_repo / "escape.h").symlink_to("/etc/passwd")
            subprocess.run(["git", "-C", str(source_repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(source_repo), "commit", "-m", "fixture"],
                           check=True, capture_output=True)
            subprocess.run(
                ["git", "-C", str(source_repo), "checkout", "-b", "release/v1"],
                check=True, capture_output=True)
            nested = source_repo / "nested dir"
            nested.mkdir()
            (nested / "packet type.h").write_text(
                "struct packet_type { int value; };")
            subprocess.run(["git", "-C", str(source_repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(source_repo), "commit",
                            "-m", "nested source"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(source_repo), "tag", "v1.0"],
                           check=True, capture_output=True)
            commit = subprocess.run(
                ["git", "-C", str(source_repo), "rev-parse", "HEAD"],
                check=True, capture_output=True, text=True).stdout.strip()

            real_git = repository._git
            clone_destinations = []

            def clone_local_source(args, **kwargs):
                args = list(args)
                if args[0] == "clone":
                    args[-2] = str(source_repo)
                    clone_destinations.append(Path(args[-1]))
                return real_git(args, **kwargs)

            with patch.object(repository, "_git", side_effect=clone_local_source):
                source, peers = repository.fetch_sources(
                    "https://github.com/example/fixture/blob/main/packet.h", "C")
                proto_source, proto_peers = repository.fetch_sources(
                    "https://github.com/example/fixture/blob/main/service.proto", "Protobuf")
                with self.assertRaisesRegex(ValueError, "exceeds 4 bytes"):
                    repository.fetch_sources(
                        "https://github.com/example/fixture/blob/main/packet.h",
                        "C", max_bytes=4)
                nested_source, nested_peers = repository.fetch_sources(
                    "https://github.com/example/fixture/blob/release/v1/"
                    "nested%20dir/packet%20type.h", "C")
                tag_source, _ = repository.fetch_sources(
                    "https://github.com/example/fixture/blob/v1.0/"
                    "nested%20dir/packet%20type.h", "C")
                sha_source, _ = repository.fetch_sources(
                    f"https://github.com/example/fixture/blob/{commit}/"
                    "nested%20dir/packet%20type.h", "C")
                with self.assertRaisesRegex(ValueError, "does not identify"):
                    repository.fetch_sources(
                        "https://github.com/example/fixture/blob/unknown/"
                        "nested%20dir/packet%20type.h", "C")
                with self.assertRaisesRegex(ValueError, "not found"):
                    repository.fetch_sources(
                        "https://github.com/example/fixture/blob/main/missing.h", "C")
                with self.assertRaisesRegex(ValueError, "escapes the cloned repository"):
                    repository.fetch_sources(
                        "https://github.com/example/fixture/blob/main/escape.h", "C")

        self.assertEqual(source, "struct packet { struct header hdr; };")
        self.assertEqual(peers, ["struct header { int kind; };"])
        self.assertEqual(proto_source, "message Service { Child child = 1; }")
        self.assertEqual(proto_peers, ["message Child { string name = 1; }"])
        self.assertEqual(nested_source, "struct packet_type { int value; };")
        self.assertIn("struct header { int kind; };", nested_peers)
        self.assertEqual(tag_source, nested_source)
        self.assertEqual(sha_source, nested_source)
        self.assertTrue(clone_destinations)
        self.assertTrue(all(not path.exists() for path in clone_destinations))

    def test_git_command_errors_are_reported(self):
        with patch("typelink.repository.subprocess.run",
                   side_effect=subprocess.CalledProcessError(
                       128, ["git", "clone"], stderr="fatal: repository not found")):
            with self.assertRaisesRegex(ValueError, "failed: fatal: repository not found"):
                repository._git(["clone", "https://github.com/example/missing.git"])

    def test_git_timeout_is_reported(self):
        with patch("typelink.repository.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(["git", "clone"], 1)):
            with self.assertRaisesRegex(ValueError, "timed out"):
                repository._git(["clone", "https://github.com/example/slow.git"])

    def test_failed_clone_still_removes_temporary_directory(self):
        real_temp_dir = tempfile.TemporaryDirectory
        created = []

        def track_temp_dir(*args, **kwargs):
            result = real_temp_dir(*args, **kwargs)
            created.append(Path(result.name))
            return result

        with patch("typelink.repository.tempfile.TemporaryDirectory",
                   side_effect=track_temp_dir), patch.object(
                       repository, "_git", side_effect=ValueError("clone failed")):
            with self.assertRaisesRegex(ValueError, "clone failed"):
                repository.fetch_sources(
                    "https://github.com/example/fixture/blob/main/packet.h", "C")
        self.assertEqual(len(created), 1)
        self.assertFalse(created[0].exists())


class CliTests(unittest.TestCase):
    def test_expand_clone_option_is_opt_in(self):
        with tempfile.NamedTemporaryFile("w") as model:
            model.write(LINK % (
                "packet", "C",
                "https://github.com/example/fixture/blob/main/packet.h"))
            model.flush()
            for args, expected in (([], False), (["--clone-repo"], True)):
                output = StringIO()
                with self.subTest(args=args), patch(
                        "typelink.__main__.emit.expand", return_value="expanded") as expand:
                    with redirect_stdout(output):
                        self.assertEqual(main(["expand", model.name, *args]), 0)
                    self.assertEqual(output.getvalue(), "expanded")
                    self.assertIs(expand.call_args.kwargs["clone_repo"], expected)

    def test_kaitai_expands_by_default_and_supports_expanded_input(self):
        model = '''item def Packet {
    attribute kind : ScalarValues::Integer { @DataSize { bits = 8; } }
}'''
        with tempfile.NamedTemporaryFile("w") as source:
            source.write(model)
            source.flush()
            for args, should_expand in (([], True), (["--expanded"], False)):
                output = StringIO()
                with self.subTest(args=args), patch(
                        "typelink.__main__.emit.expand", return_value=model) as expand, patch(
                            "typelink.__main__.kaitai.generate", return_value="schema") as generate:
                    with redirect_stdout(output):
                        self.assertEqual(
                            main(["kaitai", source.name, "--item", "Packet", *args]), 0)
                    self.assertEqual(output.getvalue(), "schema")
                    self.assertEqual(expand.called, should_expand)
                    generate.assert_called_once()
            with tempfile.TemporaryDirectory() as directory:
                output_path = Path(directory) / "packet.ksy"
                with patch(
                        "typelink.__main__.emit.expand") as expand, patch(
                            "typelink.__main__.kaitai.generate",
                            return_value="file schema") as generate:
                    self.assertEqual(main([
                        "kaitai", source.name, "--item", "Packet", "--expanded",
                        "--output", str(output_path)]), 0)
                expand.assert_not_called()
                generate.assert_called_once()
                self.assertEqual(output_path.read_text(), "file schema")

    def test_kaitai_does_not_expose_importer_data_model_option(self):
        with tempfile.NamedTemporaryFile("w") as source, redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit) as result:
                main(["kaitai", source.name, "--data-model", "lp64"])
        self.assertEqual(result.exception.code, 2)

    def test_kaitai_recurses_into_directory_and_writes_schemas_next_to_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            nested = root / "nested"
            nested.mkdir()
            model = root / "packet.sysml"
            nested_model = nested / "child.sysml"
            model.write_text("packet model")
            nested_model.write_text("child model")
            (nested / "ignored.txt").write_text("not SysML")

            with patch("typelink.__main__.kaitai.generate",
                       side_effect=lambda text, **kwargs: "schema: " + text):
                self.assertEqual(main(["kaitai", str(root), "--expanded"]), 0)

            self.assertEqual(model.with_suffix(".ksy").read_text(), "schema: packet model")
            self.assertEqual(nested_model.with_suffix(".ksy").read_text(), "schema: child model")
            self.assertTrue((nested / "ignored.txt").exists())

    def test_kaitai_directory_output_mirrors_source_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            nested = root / "nested"
            nested.mkdir()
            model = nested / "packet.sysml"
            model.write_text("packet model")
            output_dir = root / "schemas"

            with patch("typelink.__main__.kaitai.generate", return_value="schema"):
                self.assertEqual(main([
                    "kaitai", str(root), "--expanded", "-o", str(output_dir)]), 0)

            self.assertEqual(
                (output_dir / "nested" / "packet.ksy").read_text(), "schema")
            self.assertEqual(model.read_text(), "packet model")

    def test_kaitai_directory_reports_errors_and_continues(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            broken = root / "a-broken.sysml"
            valid = root / "b-valid.sysml"
            broken.write_text("broken")
            valid.write_text("valid")
            error = StringIO()

            def generate(text, **kwargs):
                if text == "broken":
                    raise kaitai.KaitaiError("invalid model")
                return "schema"

            with patch("typelink.__main__.kaitai.generate", side_effect=generate):
                with redirect_stderr(error):
                    self.assertEqual(main(["kaitai", str(root), "--expanded"]), 1)

            self.assertFalse(broken.with_suffix(".ksy").exists())
            self.assertEqual(valid.with_suffix(".ksy").read_text(), "schema")
            self.assertIn(f"{broken}: invalid model", error.getvalue())

    def test_check_recurses_into_sysml_files_in_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            nested = root / "nested"
            nested.mkdir()
            top_model = root / "top.sysml"
            nested_model = nested / "nested.sysml"
            top_model.write_text(GOOD)
            nested_model.write_text(GOOD.replace("lell_packet", "nested_packet"))
            (nested / "ignored.txt").write_text("not SysML")
            output = StringIO()

            with redirect_stdout(output):
                self.assertEqual(main(["check", str(root)]), 0)

        results = json.loads(output.getvalue())
        self.assertEqual([result["file"] for result in results],
                         sorted([str(top_model), str(nested_model)]))
        self.assertEqual({result["file"]: result["element"] for result in results},
                         {str(top_model): "lell_packet",
                          str(nested_model): "nested_packet"})

    def test_expand_recurses_and_rewrites_sysml_files_in_place(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            nested = root / "nested"
            nested.mkdir()
            model = root / "top.sysml"
            nested_model = nested / "nested.sysml"
            model.write_text("top")
            nested_model.write_text("nested")
            (nested / "ignored.txt").write_text("untouched")
            output = StringIO()

            with patch("typelink.__main__.emit.expand",
                       side_effect=lambda text, *args, **kwargs: "expanded " + text):
                with redirect_stdout(output):
                    self.assertEqual(main(["expand", str(root)]), 0)

            self.assertEqual(model.read_text(), "expanded top")
            self.assertEqual(nested_model.read_text(), "expanded nested")
            self.assertEqual((nested / "ignored.txt").read_text(), "untouched")
            self.assertEqual(output.getvalue(), "")

    def test_expand_directory_rejects_output_file(self):
        with tempfile.TemporaryDirectory() as temp:
            error = StringIO()
            with redirect_stderr(error):
                self.assertEqual(main(["expand", temp, "-o", "output.sysml"]), 1)
        self.assertIn("cannot be used with a directory target", error.getvalue())

    def test_expand_directory_reports_errors_and_continues(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            broken = root / "a-broken.sysml"
            valid = root / "b-valid.sysml"
            broken.write_text("broken")
            valid.write_text("valid")
            error = StringIO()

            def expand(text, *args, **kwargs):
                if text == "broken":
                    raise ValueError("invalid model")
                return "expanded " + text

            with patch("typelink.__main__.emit.expand", side_effect=expand):
                with redirect_stderr(error):
                    self.assertEqual(main(["expand", str(root)]), 1)

            self.assertEqual(broken.read_text(), "broken")
            self.assertEqual(valid.read_text(), "expanded valid")
            self.assertIn(f"{broken}: invalid model", error.getvalue())


if __name__ == "__main__":
    unittest.main()

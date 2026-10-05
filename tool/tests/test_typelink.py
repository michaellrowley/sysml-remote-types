import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from typelink import emit, languages, parser, spec, sysml  # noqa: E402

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


def expand_with(origin, element, source, **kw):
    return emit.expand(LINK % (element, origin, "file:///x"), fetcher=lambda uri: source, **kw)


class SpecTests(unittest.TestCase):
    def test_spec(self):
        s = spec.load()
        self.assertEqual(s.origins, ["C", "CPP", "Protobuf"])
        self.assertEqual(s.link_attrs, {"origin": "TypeOrigin", "uri": "String"})
        self.assertEqual(s.metadata["DataSize"], {"bits": "Natural"})

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


class ExpandTests(unittest.TestCase):
    def test_c(self):
        out = expand_with("C", "pkt", C_SRC)
        self.assertIn("@DataSize { bits = 320; }", out)
        self.assertIn("item 'in' : inner_t[4] { @DataSize { bits = 32; } }", out)
        self.assertIn("item def inner_t", out)
        self.assertIn("attribute p : ScalarValues::Integer { @DataSize { bits = 64; } }", out)

    def test_data_model(self):
        out = expand_with("C", "u", C_SRC, data_model="ilp32")
        self.assertIn("@DataSize { bits = 64; }", out)
        out = expand_with("C", "u", C_SRC, data_model="lp64")
        self.assertIn("@DataSize { bits = 128; }", out)

    def test_bitfields(self):
        out = expand_with("C", "bits", C_SRC)
        self.assertIn("attribute x : ScalarValues::Integer { @DataSize { bits = 3; } }", out)
        self.assertIn("@DataSize { bits = 32; }", out)

    def test_unresolved_has_no_total(self):
        warnings = []
        out = expand_with("C", "bad", C_SRC, warn=warnings.append)
        self.assertIn("ref item u : unknown_t;", out)
        self.assertEqual(len(warnings), 1)
        self.assertNotIn("@DataSize { bits = 8; }\n    attribute", out.split("typelink:begin")[1][:60])

    def test_protobuf(self):
        out = expand_with("Protobuf", "Msg", PROTO_SRC)
        self.assertIn("attribute tags : ScalarValues::String[0..*];", out)
        self.assertIn("item def Inner", out)

    def test_idempotent(self):
        once = expand_with("C", "pkt", C_SRC)
        twice = emit.expand(once, fetcher=lambda uri: C_SRC)
        self.assertEqual(once, twice)

    def test_file_uri_and_missing(self):
        with tempfile.NamedTemporaryFile("w", suffix=".h", delete=False) as f:
            f.write(C_SRC)
        out = emit.expand(LINK % ("pkt", "C", Path(f.name).as_uri()))
        self.assertIn("bits = 320", out)
        with self.assertRaises(ValueError):
            expand_with("C", "nope", C_SRC)
        with self.assertRaises(ValueError):
            emit.expand(LINK % ("pkt", "C", Path(f.name).as_uri()), max_bytes=10)

    def test_keyword_member_quoted(self):
        out = expand_with("C", "k", "struct k { int part; };")
        self.assertIn("attribute 'part'", out)


if __name__ == "__main__":
    unittest.main()

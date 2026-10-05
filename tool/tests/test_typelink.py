import unittest

from typelink import parser, spec

GOOD = '''item def lell_packet {
    @TypeLink {
        origin = TypeOrigin::C;
        uri = "https://github.com/greatscottgadgets/libbtbb/blob/master/lib/src/bluetooth_le_packet.h";
    }
}'''


class T(unittest.TestCase):
    def test_spec(self):
        origins, attrs = spec.load()
        self.assertEqual(origins, ["C", "CPP", "Protobuf"])
        self.assertEqual(attrs, {"origin": "TypeOrigin", "uri": "String"})

    def test_rfc_in_sync(self):
        self.assertTrue(spec.sync_rfc(write=False))

    def test_good(self):
        (l,) = parser.parse(GOOD)
        self.assertEqual((l.element, l.origin), ("lell_packet", "C"))

    def test_bad(self):
        for bad in (GOOD.replace("::C", "::Rust"), GOOD.replace("origin", "orig"),
                    GOOD.replace('"https://', '"'), "item def x { @TypeLink { } }"):
            with self.assertRaises(parser.TypeLinkError):
                parser.parse(bad)


if __name__ == "__main__":
    unittest.main()

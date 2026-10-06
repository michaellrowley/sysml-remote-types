package TypeLinkMetadata {
    enum def TypeOrigin {
        doc /* Different formats for structural data that may be present
             * in the addressed URI
             */
        enum C;
        enum CPP;
        enum Protobuf;
    }
    enum def DataLayoutKind {
        enum Struct;
        enum Union;
        enum Protobuf;
    }
    enum def DataEncodingKind {
        enum Varint;
        enum Zigzag;
        enum Fixed32;
        enum Fixed64;
        enum String;
        enum Bytes;
        enum Message;
        enum Enum;
        enum Map;
        enum Group;
        enum Unresolved;
    }
    metadata def TypeLink {
        doc /* Indicates that a given item/type which uses this TypeLink will
             * act as a shallow reference to the linked type.
             */
        attribute origin : TypeOrigin;
        attribute uri : String;
    }
    metadata def DataSize {
        doc /* Size, in bits, of one instance of the annotated member, or of the
             * whole item when it annotates an item definition (including any
             * padding required by the represented layout). Absent when the size
             * is variable or unknown.
             */
        attribute bits : Natural;
    }
    metadata def DataLayout {
        doc /* Layout semantics for Kaitai generation. Struct describes an
             * offset-based layout; Union describes overlapping members;
             * Protobuf describes its tagged wire format. With no DataLayout,
             * fields are a packed sequence.
             */
        attribute kind : DataLayoutKind;
    }
    metadata def DataOffset {
        doc /* Start offset, in bits, of one member from its containing item.
             */
        attribute bits : Natural;
    }
    metadata def DataSigned {
        doc /* Signedness of an integer member in the imported type definition.
             */
        attribute value : Boolean;
    }
    metadata def DataEncoding {
        doc /* Tagged-wire information retained for Kaitai generation.
             */
        attribute field_number : Natural;
        attribute kind : DataEncodingKind;
        attribute wire_type : Natural;
        attribute source_type : String;
        attribute packed : Boolean;
    }
    metadata def DataMap {
        doc /* Key and value types for a tagged-wire map entry.
             */
        attribute key_type : String;
        attribute value_type : String;
        attribute value_kind : String;
    }
}

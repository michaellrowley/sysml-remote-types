package TypeLinkMetadata {
    enum def TypeOrigin {
        doc /* Different formats for structural data that may be present
             * in the addressed URI
             */
        enum C;
        enum CPP;
        enum Protobuf;
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
             * padding the origin's layout rules insert). Absent when the size
             * is variable or unknown.
             */
        attribute bits : Natural;
    }
}

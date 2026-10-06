item def Packet {
    item def Header {
        attribute kind : ScalarValues::Integer {
            @DataSize { bits = 8; }
        }
        attribute length : ScalarValues::Integer {
            @DataSize { bits = 16; }
        }
    }
    item header : Header {
        @DataSize { bits = 24; }
    }
    attribute payload : ScalarValues::Integer[4] {
        @DataSize { bits = 8; }
    }
}

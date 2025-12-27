#include "UdpReceiver.h"
#include <iostream>
#include <cstdint>

int main() {
    UdpReceiver rx;

    constexpr std::uint16_t port = 9000;
    if (!rx.bind(port, "0.0.0.0")) {
        std::cerr << "Failed to bind UDP port " << port << "\n";
        return 1;
    }

    std::cout << "Listening on UDP :" << port << " ...\n";

    std::uint64_t packets = 0;
    std::uint64_t bytes = 0;

    UdpPacket p;
    while (true) {
        if (!rx.recv(p)) return 1;

        packets++;
        bytes += p.data.size();

        if (packets % 100 == 0) {
            std::cout << "pkts=" << packets
                      << " total_bytes=" << bytes
                      << " last_size=" << p.data.size()
                      << " from=" << p.from_ip << ":" << p.from_port
                      << "\n";
        }
    }
}

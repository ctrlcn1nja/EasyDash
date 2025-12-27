#pragma once
#include <cstdint>
#include <string>
#include <vector>

struct UdpPacket {
    std::string from_ip;
    uint16_t from_port = 0;
    std::vector<std::uint8_t> data;
};

class UdpReceiver {
public:
    UdpReceiver();
    ~UdpReceiver();

    bool bind(uint16_t port, const char* bind_ip = "0.0.0.0");
    bool recv(UdpPacket& out); // blocking receive

private:
    int sock_ = -1;
};

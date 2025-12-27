#include "UdpReceiver.h"

#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>

#include <cerrno>
#include <cstring>
#include <iostream>

UdpReceiver::UdpReceiver() = default;

UdpReceiver::~UdpReceiver() {
    if (sock_ >= 0) {
        ::close(sock_);
        sock_ = -1;
    }
}

bool UdpReceiver::bind(uint16_t port, const char* bind_ip) {
    sock_ = ::socket(AF_INET, SOCK_DGRAM, 0);
    if (sock_ < 0) {
        std::cerr << "socket() failed: " << std::strerror(errno) << "\n";
        return false;
    }

    // Optional: allow quick restart
    int yes = 1;
    ::setsockopt(sock_, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);

    if (::inet_pton(AF_INET, bind_ip, &addr.sin_addr) != 1) {
        std::cerr << "inet_pton failed for bind_ip=" << bind_ip << "\n";
        return false;
    }

    if (::bind(sock_, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0) {
        std::cerr << "bind() failed: " << std::strerror(errno) << "\n";
        return false;
    }

    return true;
}

bool UdpReceiver::recv(UdpPacket& out) {
    std::vector<std::uint8_t> buf(4096);

    sockaddr_in from{};
    socklen_t from_len = sizeof(from);

    const int n = ::recvfrom(
        sock_,
        buf.data(),
        buf.size(),
        0,
        reinterpret_cast<sockaddr*>(&from),
        &from_len
    );

    if (n < 0) {
        std::cerr << "recvfrom() failed: " << std::strerror(errno) << "\n";
        return false;
    }

    char ip_str[INET_ADDRSTRLEN]{};
    ::inet_ntop(AF_INET, &from.sin_addr, ip_str, sizeof(ip_str));

    out.from_ip = ip_str;
    out.from_port = ntohs(from.sin_port);
    out.data.assign(buf.begin(), buf.begin() + n);
    return true;
}

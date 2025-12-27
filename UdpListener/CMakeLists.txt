cmake_minimum_required(VERSION 3.20)
project(acc_udp_listener LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_executable(acc_udp_listener
    src/main.cpp
    src/UdpReceiver.cpp
)

target_include_directories(acc_udp_listener PRIVATE src)

target_compile_options(acc_udp_listener PRIVATE -Wall -Wextra -Wpedantic)

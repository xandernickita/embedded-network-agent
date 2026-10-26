cmake_minimum_required(VERSION 3.16)
project(nda_server VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE RelWithDebInfo)
endif()

option(NDA_WERROR "Treat warnings as errors (CI turns this on)" OFF)
option(NDA_SANITIZE "Build with AddressSanitizer + UBSan" OFF)

# JSON: use the system package when present (Pi: `apt install nlohmann-json3-dev`),
# otherwise download the pinned single-header release.
find_package(nlohmann_json 3.10 QUIET)
if(NOT nlohmann_json_FOUND)
  include(FetchContent)
  if(POLICY CMP0135)
    cmake_policy(SET CMP0135 NEW)  # extracted files get extraction-time timestamps
  endif()
  FetchContent_Declare(json
    URL https://github.com/nlohmann/json/releases/download/v3.11.3/json.tar.xz
    URL_HASH SHA256=d6c65aca6b1ed68e7a182f4757257b107ae403032760ed6ef121c9d55e81757d)
  FetchContent_MakeAvailable(json)
endif()

add_library(nda_core STATIC
  src/framing.cpp
  src/protocol.cpp
  src/telemetry.cpp
  src/server.cpp)
target_include_directories(nda_core PUBLIC src)
target_link_libraries(nda_core PUBLIC nlohmann_json::nlohmann_json)
target_compile_options(nda_core PUBLIC -Wall -Wextra -Wpedantic -Wshadow -Wconversion -Wno-sign-conversion)
if(NDA_WERROR)
  target_compile_options(nda_core PUBLIC -Werror)
endif()
if(NDA_SANITIZE)
  target_compile_options(nda_core PUBLIC -fsanitize=address,undefined -fno-omit-frame-pointer)
  target_link_options(nda_core PUBLIC -fsanitize=address,undefined)
endif()

add_executable(nda-server src/main.cpp)
target_link_libraries(nda-server PRIVATE nda_core)
target_compile_definitions(nda-server PRIVATE NDA_VERSION="${PROJECT_VERSION}")
install(TARGETS nda-server RUNTIME DESTINATION bin)

enable_testing()
add_executable(nda-tests tests/test_main.cpp tests/test_framing.cpp tests/test_protocol.cpp)
target_link_libraries(nda-tests PRIVATE nda_core)
target_compile_definitions(nda-tests PRIVATE NDA_FIXTURES="${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures")
add_test(NAME unit COMMAND nda-tests)

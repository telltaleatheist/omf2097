cmake_minimum_required(VERSION 3.20)
project(omf2097 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if(NOT MSVC)
  # The simulation must give bit-identical results across machines: no fused
  # multiply-add in logic that uses floats (CLAUDE.md, Determinism).
  add_compile_options(-Wall -Wextra -ffp-contract=off)
endif()

# What the differential tests need. None of it is in the repository.
set(OMF_GAME_DIR "${CMAKE_SOURCE_DIR}/game-original/GAME" CACHE PATH "The original game's files")
set(OMF_ELF "${CMAKE_SOURCE_DIR}/analysis/master.elf" CACHE FILEPATH "From tools/build_analysis.sh")
set(OMF_PYTHON "${CMAKE_SOURCE_DIR}/.venv/bin/python" CACHE FILEPATH "Python with tests/requirements.txt")

# Game logic: plain C++, no SDL or engine types.
add_library(omf_logic STATIC src/logic/rng.cpp src/logic/compositor.cpp)
target_include_directories(omf_logic PUBLIC src)

# Parses the original's files from bytes in memory. File reading stays in the tools.
add_library(omf_assets STATIC src/assets/formats.cpp)
target_link_libraries(omf_assets PUBLIC omf_logic)

enable_testing()

add_executable(omf_tests tests/main.cpp tests/test_rng.cpp tests/test_formats.cpp tests/test_compositor.cpp)
target_link_libraries(omf_tests PRIVATE omf_assets)
add_test(NAME omf_tests COMMAND omf_tests)

add_executable(probe_rng tests/probe_rng.cpp)
target_link_libraries(probe_rng PRIVATE omf_logic)

# Exit code 77 means the game files or Python packages are missing: reported as skipped.
add_test(NAME differential_rng
         COMMAND ${CMAKE_SOURCE_DIR}/tests/differential/run.sh ${OMF_PYTHON}
                 ${CMAKE_SOURCE_DIR}/tests/differential/test_rng.py
                 --probe $<TARGET_FILE:probe_rng> --elf ${OMF_ELF}
                 --random-dat ${OMF_GAME_DIR}/RANDOM.DAT)
add_test(NAME break_rng
         COMMAND ${CMAKE_SOURCE_DIR}/tests/differential/run.sh ${OMF_PYTHON}
                 ${CMAKE_SOURCE_DIR}/tests/differential/break_rng.py
                 --cxx ${CMAKE_CXX_COMPILER} --elf ${OMF_ELF}
                 --random-dat ${OMF_GAME_DIR}/RANDOM.DAT)
add_executable(probe_compositor tests/probe_compositor.cpp)
target_link_libraries(probe_compositor PRIVATE omf_assets)

add_test(NAME differential_formats
         COMMAND ${CMAKE_SOURCE_DIR}/tests/differential/run.sh ${OMF_PYTHON}
                 ${CMAKE_SOURCE_DIR}/tests/differential/test_formats.py
                 --probe $<TARGET_FILE:probe_compositor> --elf ${OMF_ELF} --game ${OMF_GAME_DIR})
add_test(NAME differential_compositor
         COMMAND ${CMAKE_SOURCE_DIR}/tests/differential/run.sh ${OMF_PYTHON}
                 ${CMAKE_SOURCE_DIR}/tests/differential/test_compositor.py
                 --probe $<TARGET_FILE:probe_compositor> --elf ${OMF_ELF} --game ${OMF_GAME_DIR})
add_test(NAME break_compositor
         COMMAND ${CMAKE_SOURCE_DIR}/tests/differential/run.sh ${OMF_PYTHON}
                 ${CMAKE_SOURCE_DIR}/tests/differential/break_compositor.py
                 --cxx ${CMAKE_CXX_COMPILER} --elf ${OMF_ELF} --game ${OMF_GAME_DIR})
set_tests_properties(differential_rng break_rng differential_formats differential_compositor break_compositor
                     PROPERTIES SKIP_RETURN_CODE 77)

# A visual check: composes one arena and fighter frame through the port.
add_executable(compose_frame tools/compose_frame.cpp)
target_link_libraries(compose_frame PRIVATE omf_assets)

cmake_minimum_required(VERSION 3.24)
project(triage-nasa CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Performance flags per the dossier: -O3 -ffast-math -march=native
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()
add_compile_options(-O3 -ffast-math -march=native)

# ---------------------------------------------------------------------------
# The C++ solver slots in later: targets are defined only when its sources
# exist. Until then the Python layer runs on the NumPy reference mock
# (src/python/sim_bridge.py), and this configure step is a clean no-op.
# ---------------------------------------------------------------------------
set(SOLVER_SOURCES
  ${CMAKE_CURRENT_SOURCE_DIR}/src/cpp/physics_solver.cpp
  ${CMAKE_CURRENT_SOURCE_DIR}/src/cpp/adi_solver.cpp
  ${CMAKE_CURRENT_SOURCE_DIR}/src/cpp/thomas_algorithm.cpp
)

set(SOLVER_SOURCES_EXIST TRUE)
foreach(SRC IN LISTS SOLVER_SOURCES)
  if(NOT EXISTS "${SRC}")
    set(SOLVER_SOURCES_EXIST FALSE)
  endif()
endforeach()

if(NOT SOLVER_SOURCES_EXIST)
  message(STATUS "src/cpp/ solver sources not present yet; backend uses the NumPy reference mock.")
  return()
endif()

find_package(pybind11 QUIET CONFIG)

if(NOT pybind11_FOUND)
  message(STATUS "pybind11 not found; run: pip install pybind11")
  message(STATUS "Falling back to a plain object library (no Python module).")
  add_library(triage_core_objs STATIC ${SOLVER_SOURCES})
  target_include_directories(triage_core_objs PRIVATE src/cpp)
  return()
endif()

# pybind11 module: `import triage_core` from the build directory.
pybind11_add_module(triage_core MODULE
  ${SOLVER_SOURCES}
  ${CMAKE_CURRENT_SOURCE_DIR}/src/cpp/bindings.cpp
)
target_include_directories(triage_core PRIVATE src/cpp)
set_target_properties(triage_core PROPERTIES
  LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}
)

# Self-tests for the Thomas algorithm (added by the solver author).
enable_testing()
// A minimal test runner: no dependencies, so the tests build anywhere the game does.
#pragma once

#include <cstdio>
#include <functional>
#include <utility>
#include <vector>

namespace check {

struct Test {
  const char* name;
  std::function<void()> fn;
};

std::vector<Test>& registry();
extern int failures;

struct Register {
  Register(const char* name, std::function<void()> fn) { registry().push_back({name, std::move(fn)}); }
};

}  // namespace check

#define CHECK_CAT2(a, b) a##b
#define CHECK_CAT(a, b) CHECK_CAT2(a, b)
#define TEST(name)                                                  \
  static void CHECK_CAT(test_, __LINE__)();                         \
  static check::Register CHECK_CAT(reg_, __LINE__)(name, CHECK_CAT(test_, __LINE__)); \
  static void CHECK_CAT(test_, __LINE__)()

#define CHECK(cond)                                                 \
  do {                                                              \
    if (!(cond)) {                                                  \
      std::printf("  %s:%d: failed: %s\n", __FILE__, __LINE__, #cond); \
      ++check::failures;                                            \
    }                                                               \
  } while (0)

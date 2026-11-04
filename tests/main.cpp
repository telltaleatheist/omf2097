#include "check.h"

namespace check {

std::vector<Test>& registry() {
  static std::vector<Test> tests;
  return tests;
}

int failures = 0;

}  // namespace check

int main() {
  for (const check::Test& test : check::registry()) {
    std::printf("%s\n", test.name);
    test.fn();
  }
  std::printf("%zu tests, %d failures\n", check::registry().size(), check::failures);
  return check::failures == 0 ? 0 : 1;
}

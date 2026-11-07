// SPDX-License-Identifier: Apache-2.0
namespace watch_tree;
root struct Tree { _state: i64[2] = [0; 2] }
extern fn begin(tree: i64[:]) -> i64 = "honk_tree_begin";
extern fn root(tree: i64[:], path: const u8[:]) -> i64 = "honk_tree_root";
extern fn scan_step(tree: i64[:]) -> i64 = "honk_tree_scan_step";
extern fn verify_begin(tree: i64[:]) -> i64 = "honk_tree_verify_begin";
extern fn verify_step(tree: i64[:]) -> i64 = "honk_tree_verify_step";
extern fn fds(tree: i64[:], descriptors: i64[:]) -> i64 = "honk_tree_fds";
extern fn roots_valid(tree: i64[:]) -> i64 = "honk_tree_roots_valid";
extern fn guard_event(tree: i64[:], index: i64, name: const u8[:], mask: i64) -> i64 = "honk_tree_guard_event";
extern fn event(tree: i64[:], index: i64, name: const u8[:], mask: i64) -> i64 = "honk_tree_event";
extern fn close_native(tree: i64[:]) -> i64 = "honk_tree_close";
fn close(tree: Tree&) -> bool {
    if tree._state[0] == 0 { return true; }
    return close_native(tree._state) == 0;
}

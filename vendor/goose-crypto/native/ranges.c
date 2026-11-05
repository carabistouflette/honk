/* SPDX-License-Identifier: Apache-2.0 */
#include "crypto.h"
#include <stddef.h>
#include <stdint.h>
/* Only compare addresses, never dereference them. Empty ranges do not overlap. */
int64_t gc_disjoint(gc_input input, gc_output output) {
    if (input.len < 0 || output.len < 0 ||
        (uint64_t)input.len > SIZE_MAX || (uint64_t)output.len > SIZE_MAX ||
        (input.len && (!input.data || (uintptr_t)input.data > UINTPTR_MAX - (uint64_t)input.len)) ||
        (output.len && (!output.data || (uintptr_t)output.data > UINTPTR_MAX - (uint64_t)output.len))) return 1;
    if (!input.len || !output.len) return 0;
    uintptr_t a = (uintptr_t)input.data, b = (uintptr_t)output.data;
    return a <= b ? b - a < (uint64_t)input.len : a - b < (uint64_t)output.len;
}

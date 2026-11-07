/* SPDX-License-Identifier: Apache-2.0 */
/* Observation only: no synthetic records, no changes to watch status/metadata. */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdlib.h>
#include <unistd.h>
typedef struct { int64_t *data; int64_t len; } ints;
typedef struct { uint8_t *data; int64_t len; } bytes;
int64_t __real_gw_set_next(ints, ints, bytes, int64_t, bytes, ints) __attribute__((weak));
int64_t __wrap_gw_set_next(ints state, ints map, bytes buffer, int64_t timeout, bytes name, ints meta) {
    int64_t code=__real_gw_set_next ? __real_gw_set_next(state,map,buffer,timeout,name,meta) : 4;
    if(code==0 && meta.len==8 && meta.data && meta.data[2] && (meta.data[3]&16384) && state.len==8 && state.data){
        const char *path=getenv("WATCH_OVERFLOW_RECORD");
        if(path){
            int saved=errno;
            int fd=open(path,O_WRONLY|O_CREAT|O_APPEND|O_CLOEXEC|O_NOFOLLOW,0600);
            if(fd>=0){
                /* Fixed four-i64 record: fd+1,watch count,mask,origin. */
                int64_t record[4]={state.data[0],state.data[1],meta.data[3],meta.data[6]};
                const uint8_t *at=(const uint8_t *)record;size_t left=sizeof record;
                while(left){ssize_t n=write(fd,at,left);if(n<0 && errno==EINTR)continue;if(n<=0)break;at+=n;left-=(size_t)n;}
                close(fd);
            }
            errno=saved;
        }
    }
    return code;
}

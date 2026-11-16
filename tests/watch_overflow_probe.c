/* SPDX-License-Identifier: Apache-2.0 */
#define _POSIX_C_SOURCE 200809L
#include "../bench/watch_overflow.c"
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
static int64_t status;
static int calls;
int64_t __real_gw_set_next(ints s,ints m,bytes b,int64_t t,bytes n,ints out){
    (void)s;(void)m;(void)b;(void)t;(void)n;(void)out;
    calls++;errno=ERANGE;return status;
}
static void require(int ok,const char *message){if(!ok){perror(message);exit(1);}}
int main(void){
    char path[]="/tmp/honk-overflow-control-XXXXXX";
    int fd=mkstemp(path);require(fd>=0,"mkstemp");close(fd);
    require(setenv("WATCH_OVERFLOW_RECORD",path,1)==0,"setenv");
    int64_t s[8]={42,2},m[8]={0},original_s[8],original_m[8];
    m[2]=1;m[3]=16384;m[6]=-1;
    memcpy(original_s,s,sizeof s);memcpy(original_m,m,sizeof m);
    ints state={s,8},meta={m,8},empty={NULL,0};bytes no_bytes={NULL,0};
    require(__wrap_gw_set_next(state,empty,no_bytes,0,no_bytes,meta)==0,"status");
    require(errno==ERANGE && calls==1,"errno/call preservation");
    require(memcmp(s,original_s,sizeof s)==0 && memcmp(m,original_m,sizeof m)==0,"metadata preservation");
    int64_t actual[4],expected[4]={42,2,16384,-1};
    fd=open(path,O_RDONLY);require(fd>=0,"read open");
    require(read(fd,actual,sizeof actual)==sizeof actual && memcmp(actual,expected,sizeof actual)==0,"record");close(fd);
    struct stat before,after;require(stat(path,&before)==0,"stat");
    status=4;require(__wrap_gw_set_next(state,empty,no_bytes,0,no_bytes,meta)==4,"failure status");
    status=0;m[2]=0;require(__wrap_gw_set_next(state,empty,no_bytes,0,no_bytes,meta)==0,"not ready status");
    require(stat(path,&after)==0 && before.st_size==after.st_size,"non-overflow silence");
    m[2]=1;require(unlink(path)==0 && symlink("/dev/null",path)==0,"symlink setup");
    require(__wrap_gw_set_next(state,empty,no_bytes,0,no_bytes,meta)==0 && errno==ERANGE,"observation failure preserves result");
    require(lstat(path,&after)==0 && S_ISLNK(after.st_mode),"symlink not followed");
    require(unlink(path)==0,"cleanup");
    puts("overflow observer controls passed");
    return 0;
}

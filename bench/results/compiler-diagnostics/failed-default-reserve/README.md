# Incomplete profiling attempt

The initial runner at source 6890ff0 built default-reservation baseline/candidate
executables. Valgrind failed before application work with `cannot reserve data
stack address space`. The retained raw log records that failed attempt; it is not
an allocation measurement of the check operation. The combined report was not
completed, and no timing conclusion is drawn from that attempt. The final runner
uses separate 16 MiB stack-reservation executables for allocation profiling and
keeps default-reservation executables for timing. Production settings are unchanged.

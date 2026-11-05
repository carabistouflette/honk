# Third-party notices

No third-party source or dependencies are vendored. Goose and its standard
library are build/runtime prerequisites, fetched at the exact GOOSE_REVISION;
their licenses remain in the compiler distribution. RFC 3339 is referenced for
format semantics; no RFC text or reference implementation is included.

Calendar conversion uses arithmetic Gregorian cycles (400 years / 146097 days)
and the number of days before 1970, with bounded month iteration. Tests use
Python's standard-library datetime as an independent development-only oracle.

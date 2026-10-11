# Extra files for the `geo` Lambda layer

`deploy.py` copies everything under this folder into the root of the geo layer, next to `python/`. Files in `lib/`
end up in `/opt/lib`, which is on the Lambda runtime's library path.

- `lib/libexpat.so.1`: Expat 2.8.3 from the Amazon Linux 2023 package `expat-2.8.3-1.amzn2023.0.1.x86_64`. The GDAL
  library inside the rasterio 1.4.3 wheel links against the system `libexpat.so.1`, which the Lambda `python3.12`
  runtime (Amazon Linux 2023) does not include, so without it the geo function fails with
  `Runtime.ImportModuleError: libexpat.so.1: cannot open shared object file`. Expat is MIT-licensed; its licence is in
  `lib/EXPAT-COPYING.txt`.

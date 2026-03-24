Build the MicroPython 1.24 firmware UF2 for the Raspberry Pi Pico W.

Run the following two commands in sequence:

1. Build the Docker image:
```
docker build -t bilalcast-rp2 -f Dockerfile.micropython.1.24.rp2 .
```

2. Run the build to produce the UF2:
```
docker run -v $(pwd):/tmp/bilalcast-build bilalcast-rp2
```

Tell the user when the build is complete and where to find the UF2 output file.

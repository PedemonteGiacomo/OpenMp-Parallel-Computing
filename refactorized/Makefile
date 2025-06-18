CC      = gcc
CFLAGS  = -O2 -fopenmp
LIBS    = -lm          # <-- aggiungi libm

all: grayscale

grayscale: main.c parallel_to_grayscale.c parallel_to_grayscale.h
	$(CC) $(CFLAGS) $^ -o $@ $(LIBS)

clean:
	rm -f grayscale

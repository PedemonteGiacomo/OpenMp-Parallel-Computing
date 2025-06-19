// parallel_to_grayscale.c
#include <omp.h>
#include "parallel_to_grayscale.h"

void convert_to_grayscale(unsigned char *data, int width, int height, int channels) {
    int numPixels = width * height;
    #pragma omp parallel for
    for (int i = 0; i < numPixels; i++) {
        int idx = i * channels;
        unsigned char r = data[idx];
        unsigned char g = data[idx+1];
        unsigned char b = data[idx+2];
        unsigned char lum = (unsigned char)(0.299f*r + 0.587f*g + 0.114f*b);
        data[idx] = data[idx+1] = data[idx+2] = lum;
        // se c'è canale alpha (channels==4), rimane invariato
    }
}

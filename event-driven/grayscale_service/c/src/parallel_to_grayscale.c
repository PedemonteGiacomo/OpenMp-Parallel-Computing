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

void convert_to_grayscale_multi_pass(unsigned char *data, int width, int height, int channels, int passes) {
    // Simulate a computationally intensive algorithm with multiple passes
    for (int pass = 0; pass < passes; pass++) {
        int numPixels = width * height;
        
        // Alternating passes use slightly different algorithms to ensure
        // the compiler doesn't optimize away the computation
        if (pass % 2 == 0) {
            // Standard luminance conversion
            #pragma omp parallel for
            for (int i = 0; i < numPixels; i++) {
                int idx = i * channels;
                unsigned char r = data[idx];
                unsigned char g = data[idx+1];
                unsigned char b = data[idx+2];
                // Standard RGB to grayscale conversion
                unsigned char lum = (unsigned char)(0.299f*r + 0.587f*g + 0.114f*b);
                data[idx] = data[idx+1] = data[idx+2] = lum;
            }
        } else {
            // Alternative algorithm (e.g., weighted average with different coefficients)
            #pragma omp parallel for
            for (int i = 0; i < numPixels; i++) {
                int idx = i * channels;
                unsigned char r = data[idx];
                unsigned char g = data[idx+1];
                unsigned char b = data[idx+2];
                // Different coefficients to ensure computation isn't optimized away
                unsigned char lum = (unsigned char)(0.333f*r + 0.333f*g + 0.333f*b);
                data[idx] = data[idx+1] = data[idx+2] = lum;
            }
        }
    }
}

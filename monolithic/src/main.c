// main.c
#define _POSIX_C_SOURCE 200809L

#define STB_IMAGE_IMPLEMENTATION
#include "stb_image.h"
#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "stb_image_write.h"

#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include "parallel_to_grayscale.h"

int main(int argc, char *argv[]) {
    if (argc < 3) {
        fprintf(stderr, "Uso: %s <input_img> <output_img.png> [passaggi_kernel]\n", argv[0]);
        return 1;
    }

    int width, height, channels;
    unsigned char *img = stbi_load(argv[1], &width, &height, &channels, 0);
    if (!img) {
        fprintf(stderr, "Errore caricando immagine\n");
        return 1;
    }

    int passes = (argc >= 4) ? atoi(argv[3]) : 1;
    if (passes < 1) passes = 1;

    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);

    for (int p = 0; p < passes; ++p) {
        convert_to_grayscale(img, width, height, channels);
    }

    clock_gettime(CLOCK_MONOTONIC, &t1);
    double secs = (t1.tv_sec - t0.tv_sec) + (t1.tv_nsec - t0.tv_nsec) / 1e9;
    printf("Compute kernel ×%d: %.4f s\n", passes, secs);

    if (!stbi_write_png(argv[2], width, height, channels, img, width * channels)) {
        fprintf(stderr, "Errore nel salvataggio\n");
        stbi_image_free(img);
        return 1;
    }

    stbi_image_free(img);
    return 0;
}

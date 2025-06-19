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
#include "sobel.h"

int main(int argc, char *argv[])
{
    if (argc < 3) {
        fprintf(stderr,
                "Uso: %s <input_img> <output_img.png> [passaggi_kernel]\n",
                argv[0]);
        return 1;
    }

    /* ------------------------------------------------------------------ */
    /* Carica l’immagine                                                  */
    int width, height, channels;
    unsigned char *img =
        stbi_load(argv[1], &width, &height, &channels, 0);
    if (!img) {
        fprintf(stderr, "Errore caricando l'immagine \"%s\"\n", argv[1]);
        return 1;
    }

    const long numPix = (long)width * height;
    unsigned char *gray = malloc(numPix);      /* 1 byte / pixel */
    unsigned char *edge = malloc(numPix);      /* 1 byte / pixel */
    if (!gray || !edge) {
        fprintf(stderr, "Impossibile allocare buffer temporanei\n");
        free(gray); free(edge); stbi_image_free(img);
        return 1;
    }

    int passes = (argc >= 4) ? atoi(argv[3]) : 1;
    if (passes < 1) passes = 1;

    /* ------------------------------------------------------------------ */
    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);

    for (int p = 0; p < passes; ++p) {

        /* 1) scala di grigi in-place (RGB → Y in tutti i canali) */
        convert_to_grayscale(img, width, height, channels);

        /* 2) estrai un piano mono-canale in gray[]                */
        #pragma omp parallel for schedule(static)
        for (long i = 0; i < numPix; ++i)
            gray[i] = img[i * channels];   /* R == G == B a questo punto */

        /* 3) filtro Sobel su gray → edge                            */
        sobel_edge(gray, edge, width, height);

        /* 4) ricopia edge nei 3 canali RGB per poter salvare PNG     */
        #pragma omp parallel for schedule(static)
        for (long i = 0; i < numPix; ++i) {
            unsigned char e = edge[i];
            long idx = i * channels;
            img[idx]     = e;
            img[idx + 1] = e;
            img[idx + 2] = e;
            /* eventuale canale alpha (idx+3) lasciato invariato      */
        }
    }

    clock_gettime(CLOCK_MONOTONIC, &t1);
    double secs = (t1.tv_sec - t0.tv_sec) +
                  (t1.tv_nsec - t0.tv_nsec) / 1e9;
    printf("Compute kernel (grayscale + sobel) ×%d: %.4f s\n",
           passes, secs);

    /* ------------------------------------------------------------------ */
    if (!stbi_write_png(argv[2], width, height, channels,
                        img, width * channels)) {
        fprintf(stderr, "Errore nel salvataggio di \"%s\"\n", argv[2]);
    }

    free(gray);
    free(edge);
    stbi_image_free(img);
    return 0;
}

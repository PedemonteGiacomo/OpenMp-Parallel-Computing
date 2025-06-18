// main.c
#define _POSIX_C_SOURCE 200809L   /* o 199309L, entrambe funzionano */

#define STB_IMAGE_IMPLEMENTATION
#include "stb_image.h"
#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "stb_image_write.h"

#include <stdio.h>
#include <time.h>                  // <-- aggiunto
#include "parallel_to_grayscale.h"

int main(int argc, char *argv[]) {
    if (argc < 3) {
        printf("Uso: %s input_image output_image.png\n", argv[0]);
        return 1;
    }

    int width, height, channels;
    unsigned char *img = stbi_load(argv[1], &width, &height, &channels, 0);
    if (!img) {
        printf("Errore caricando l'immagine\n");
        return 1;
    }

    /* ---- misura solo il kernel OpenMP ----------------------------------- */
    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);

    convert_to_grayscale(img, width, height, channels);

    clock_gettime(CLOCK_MONOTONIC, &t1);
    double secs = (t1.tv_sec - t0.tv_sec) +
                  (t1.tv_nsec - t0.tv_nsec) / 1e9;
    printf("Compute kernel: %.4f s\n", secs);
    /* --------------------------------------------------------------------- */

    /* Salva PNG (facoltativo: puoi commentare per escludere l’I/O) */
    if (!stbi_write_png(argv[2], width, height, channels, img, width * channels)) {
        printf("Errore nel salvataggio\n");
        stbi_image_free(img);
        return 1;
    }

    stbi_image_free(img);
    return 0;
}

// main.c
#define STB_IMAGE_IMPLEMENTATION
#include "stb_image.h"
#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "stb_image_write.h"
#include <stdio.h>
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
    convert_to_grayscale(img, width, height, channels);
    // Salva in PNG (mantiene canali originali)
    if (!stbi_write_png(argv[2], width, height, channels, img, width*channels)) {
        printf("Errore nel salvataggio\n");
        stbi_image_free(img);
        return 1;
    }
    stbi_image_free(img);
    return 0;
}

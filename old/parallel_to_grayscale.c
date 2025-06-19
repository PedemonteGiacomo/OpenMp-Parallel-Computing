#include <stdlib.h>
#include <stdio.h>
#include <omp.h>

#include "utils.h"

void parallel_to_grayscale(long img[DIM_ROW][DIM_COL][DIM_RGB], long ***grayscale_img, long *min_max_gray) {
    int row, col, pixel, gray_pixel;  
    int min_gray = 256;
    int max_gray = -1;

#pragma omp parallel for collapse(2) reduction(min:min_gray) reduction(max:max_gray)
    for (int row = 0; row < DIM_ROW; row++) {
        for (int col = 0; col < DIM_COL; col++) {
            int sum = 0;
            for (int pixel = 0; pixel < DIM_RGB; pixel++) {
                sum += img[row][col][pixel];
            }
            int grayscale_value = sum / 3;
            grayscale_img[row][col][0] = grayscale_value;
            grayscale_img[row][col][1] = grayscale_value;
            grayscale_img[row][col][2] = grayscale_value;
	    if(grayscale_value > min_gray && grayscale_value < max_gray){
	      continue;
	    }

	    if (grayscale_value < min_gray) {
                min_gray = grayscale_value;
            }
            if (grayscale_value > max_gray) {
                max_gray = grayscale_value;
            }
        }
    }

    min_max_gray[0] = min_gray;
    min_max_gray[1] = max_gray;
}

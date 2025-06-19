#include <stdlib.h>
#include <stdio.h>
#include "utils.h"

void parallel_avg_pixel(long img[DIM_ROW][DIM_COL][DIM_RGB], long *avgs) {
    int row, col, pixel;
    long count = 0;
    count = DIM_ROW * DIM_COL * DIM_RGB;
    //make private count variables for each R,G,B
    long count1 = 0;
    long count2 = 0;
    long count3 = 0;

#pragma omp parallel
    {
#pragma omp for collapse(2) reduction(+:count1, count2, count3)
        for (row = 0; row < DIM_ROW; row++) {
            for (col = 0; col < DIM_COL; col++) {
                for (pixel = 0; pixel < DIM_RGB; pixel++) {
		    count1 += img[row][col][0];
                    count2 += img[row][col][1];
                    count3 += img[row][col][2];
                }
            }
        }
	    #pragma omp single
	{
            avgs[0] += count1;
            avgs[1] += count2;
            avgs[2] += count3;
	}
    }

    count1 /= 3;
    count2 /= 3;
    count3 /= 3;
    
#pragma omp parallel for
        for (pixel = 0; pixel < DIM_RGB; pixel++) {
            avgs[pixel] /= count;
        }
}

#include <stdlib.h>
#include <math.h>
#include <omp.h>
#include "sobel.h"

void sobel_edge(const unsigned char *src,
                unsigned char *dst,
                int w, int h)
{
#pragma omp parallel for collapse(2) schedule(static)
    for (int y = 1; y < h-1; ++y) {
        for (int x = 1; x < w-1; ++x) {
            int idx = y*w + x;
            int gx =
                -src[idx-w-1] - 2*src[idx-1] - src[idx+w-1] +
                 src[idx-w+1] + 2*src[idx+1] + src[idx+w+1];
            int gy =
                 src[idx-w-1] + 2*src[idx-w] + src[idx-w+1] -
                 src[idx+w-1] - 2*src[idx+w] - src[idx+w+1];
            int mag = (int)sqrtf((float)(gx*gx + gy*gy));
            if (mag > 255) mag = 255;
            dst[idx] = (unsigned char)mag;
        }
    }
}

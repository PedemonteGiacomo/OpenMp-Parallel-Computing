// parallel_to_grayscale.h
#ifndef PARALLEL_TO_GRAYSCALE_H
#define PARALLEL_TO_GRAYSCALE_H
void convert_to_grayscale(unsigned char *data, int width, int height, int channels);
// Added new version with multiple passes support
void convert_to_grayscale_multi_pass(unsigned char *data, int width, int height, int channels, int passes);
#endif

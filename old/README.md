# OpenMp-Parallel-Computing
Parallel computing is a type of computation in which multiple tasks or processes are executed simultaneously, allowing a program to complete tasks more quickly by dividing them into smaller subtasks that can be performed concurrently.  Benefits of parallel computing include faster execution of tasks, the ability to handle more complex problems, and improved efficiency in utilizing modern hardware.

## Summary of this project: 
The code provided demonstrates how to leverage parallelism using OpenMP to enhance the performance of image processing tasks. Parallel processing is crucial in image processing due to the computational demands of working with large images and complex operations. By efficiently distributing the workload across multiple threads, these code segments optimize the processing of images and contribute to faster and more efficient image manipulation and analysis.

### Parallel Average Pixel Calculation:
This code segment is designed to calculate the average pixel values of a 3-dimensional color image. The image is represented as an array of dimensions DIM_ROW × DIM_COL × DIM_RGB, where DIM_ROW represents the number of rows, DIM_COL represents the number of columns, and DIM_RGB represents the number of color channels (typically 3 for RGB images). The code uses OpenMP parallelization to distribute the calculation of average pixel values across multiple threads. However, there are errors in the placement of operations, particularly the division for computing averages and the accumulation of pixel values across threads, which need to be corrected to achieve accurate results.

### Parallel Grayscale Conversion with Min-Max Calculation:
This code segment converts a color image into grayscale and calculates the minimum and maximum grayscale values. The original image is represented as a 3-dimensional array with dimensions DIM_ROW × DIM_COL × DIM_RGB. The grayscale version of the image is produced by averaging the RGB channel values for each pixel. OpenMP parallelization is employed to process the image in parallel and compute the minimum and maximum grayscale values concurrently. The parallelization is correctly implemented, and the code efficiently transforms the image while computing the required statistics.

### Parallel Convolution with Kernel:
This code segment applies convolution to an image using a specified kernel matrix. The original image is represented as a 3-dimensional array with dimensions DIM_ROW+PAD × DIM_COL+PAD × DIM_RGB, where padding (PAD) is added around the image to accommodate convolution. The convolution operation involves sliding the kernel over the image and computing the element-wise multiplication of the kernel and the corresponding image region, followed by accumulation. OpenMP parallelization is utilized to distribute the convolution computations across multiple threads, effectively accelerating the convolution process.

## Note

The programs in this folder are kept for historical reference. The
actively maintained implementation and benchmark script live in
`../monolithic/`.

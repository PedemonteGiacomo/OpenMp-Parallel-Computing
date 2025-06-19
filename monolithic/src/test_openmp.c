// test_openmp.c
#include <stdio.h>
#ifdef _OPENMP
#include <omp.h>
#endif

int main() {
#ifdef _OPENMP
    printf("OpenMP is supported! Version: %d\n", _OPENMP);
#else
    printf("OpenMP is NOT supported.\n");
#endif
    return 0;
}
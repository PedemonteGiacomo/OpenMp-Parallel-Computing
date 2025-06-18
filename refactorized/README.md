# Verificare la presenza di OpenMP

Per provare openmp:

    gcc -fopenmp test_openmp.c -o test_openmp && ./test_openmp

Per provare senza:

    gcc test_openmp.c -o test_openmp && ./test_openmp
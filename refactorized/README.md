# Verificare la presenza di OpenMP

Per provare openmp:

    gcc -fopenmp test_openmp.c -o test_openmp && ./test_openmp

Per provare senza:

    gcc test_openmp.c -o test_openmp && ./test_openmp

# Come testare greyscale

./bench_and_plot_monolithic.sh IMG.jpg ["1 2 4 8"] [num_run] [passaggi_kernel]


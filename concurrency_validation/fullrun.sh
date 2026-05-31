python3 concurrency_validation/test_runner.py \
  --test-dir concurrency_validation/alecci_benchmarks/SCTBench \
  --output-csv concurrency_validation/results/sct_results.csv \
  --output-latex-cm concurrency_validation/results/sct_confusion_matrix.tex \
  -j 24

python3 concurrency_validation/test_runner.py \
  --test-dir concurrency_validation/alecci_benchmarks/labeled_benchmarks \
  --output-csv concurrency_validation/results/labeled_results.csv \
  --output-latex concurrency_validation/results/labeled_table.tex \
  --output-latex-cm concurrency_validation/results/labeled_confusion_matrix.tex \
  -j 24

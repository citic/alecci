python3 concurrency_validation/test_runner.py \
  --test-dir concurrency_validation/alecci_benchmarks/SCTBench \
  --output-csv concurrency_validation/results/sct_results.csv \
  -j 24

python3 concurrency_validation/test_runner.py \
  --test-dir concurrency_validation/alecci_benchmarks/labeled_benchmarks \
  --output-csv concurrency_validation/results/labeled_results.csv \
  --output-latex concurrency_validation/results/labeled_table.tex \
  -j 24

# Combined confusion matrix (labeled + SCTBench in one table)
python3 concurrency_validation/test_runner.py \
  --from-csv \
    concurrency_validation/results/labeled_results.csv \
    concurrency_validation/results/sct_results.csv \
  --output-latex-cm concurrency_validation/results/confusion_matrix.tex

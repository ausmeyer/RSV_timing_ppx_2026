#!/usr/bin/env Rscript

required <- c(
  "tidyverse", "yaml", "lubridate", "ggridges", "cowplot", "sf", "tigris"
)
missing <- required[!vapply(required, requireNamespace, logical(1), quietly = TRUE)]
if (length(missing)) {
  install.packages(missing, repos = "https://cloud.r-project.org")
}

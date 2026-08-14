#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(dplyr)
  library(sf)
  library(tigris)
  library(yaml)
})

root <- normalizePath(getwd(), winslash = "/", mustWork = TRUE)
config <- yaml::read_yaml(file.path(root, "config.yaml"))
geometry_cfg <- config$analysis_data$state_geometry
raw_dir <- file.path(root, "data", "raw")
source_path <- file.path(raw_dir, geometry_cfg$source_filename)
output_path <- file.path(raw_dir, geometry_cfg$filename)
refresh <- "--refresh" %in% commandArgs(trailingOnly = TRUE)
keep <- c(state.name, "District of Columbia")

validate_geometry <- function(states) {
  missing_states <- setdiff(keep, states$NAME)
  if (nrow(states) != length(keep) || length(missing_states)) {
    stop(paste(
      "Census state geometry must contain exactly 50 states and DC; missing:",
      paste(missing_states, collapse = ", ")
    ))
  }
  invisible(states)
}

if (file.exists(output_path) && !refresh) {
  validate_geometry(readRDS(output_path))
  message("Prepared state geometry is ready: ", output_path)
  quit(status = 0)
}
if (!file.exists(source_path)) {
  stop("Missing Census state-geometry source. Run `make data` first.")
}

dir.create(raw_dir, recursive = TRUE, showWarnings = FALSE)
cache_dir <- file.path(raw_dir, "tigris_cache")
dir.create(cache_dir, recursive = TRUE, showWarnings = FALSE)
Sys.setenv(TIGRIS_CACHE_DIR = cache_dir)
options(tigris_use_cache = TRUE)

archive_path <- paste0(
  "/vsizip/",
  normalizePath(source_path, winslash = "/", mustWork = TRUE)
)
states <- suppressWarnings(sf::st_read(archive_path, quiet = TRUE)) |>
  filter(NAME %in% keep)
validate_geometry(states)

shifted <- tigris::shift_geometry(states)
validate_geometry(shifted)
saveRDS(shifted, output_path)
message("Prepared state geometry is ready: ", output_path)

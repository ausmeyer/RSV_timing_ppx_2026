#!/usr/bin/env Rscript
#
# figures.R — 2025-26 Season Extension
#
# Generates publication figures:
#   Figure 1: State choropleth grid (3 NSSP + available NHSN panels)
#   Figure 2: Ridgeline density plots by season and age group (ggridges)
#             - Layout A: seasons as ridgelines, faceted by age group
#             - Layout B: age groups as ridgelines, faceted by season
#   Figure 3: Realistic-delivery infant prophylaxis fractional protection
#             with 12-month exposure censor
#   Figure 4: Realistic-delivery infant prophylaxis fractional protection
#             with 8-month exposure censor
#   Figure 5: Robustness of window gains across delivery/model assumptions
#   Supplementary: State-level time series
#

# =============================================================================
# SETUP
# =============================================================================

suppressPackageStartupMessages({
  library(tidyverse)
  library(yaml)
  library(lubridate)
})

has_cowplot <- requireNamespace("cowplot",  quietly = TRUE)
has_sf      <- requireNamespace("sf",       quietly = TRUE)
has_maps    <- requireNamespace("maps",     quietly = TRUE)
has_ridges  <- requireNamespace("ggridges", quietly = TRUE)
has_arrow   <- requireNamespace("arrow",    quietly = TRUE)

root    <- getwd()
fig_dir <- file.path(root, "results", "figures")
dir.create(fig_dir, recursive = TRUE, showWarnings = FALSE)

config <- yaml::read_yaml(file.path(root, "config.yaml"))
write_regional_plots <- isTRUE(config$output$write_regional_plots)

remove_stale_default_figures <- function() {
  stale <- c(
    "nssp_fig3_coverage_ribbon.png",
    "nssp_fig3_coverage_ribbon.pdf",
    "nssp_fig3_coverage_with_ci.png",
    "nssp_fig3_coverage_with_ci.pdf",
    "nhsn_fig3_coverage_ribbon.png",
    "nhsn_fig3_coverage_ribbon.pdf",
    "nhsn_fig3_coverage_with_ci.png",
    "nhsn_fig3_coverage_with_ci.pdf",
    "nssp_fig4_infant_ppx_fractional_protection.png",
    "nssp_fig4_infant_ppx_fractional_protection.pdf",
    "nhsn_fig4_infant_ppx_fractional_protection.png",
    "nhsn_fig4_infant_ppx_fractional_protection.pdf",
    "nssp_fig5_infant_ppx_9mo_fractional_protection.png",
    "nssp_fig5_infant_ppx_9mo_fractional_protection.pdf",
    "nhsn_fig5_infant_ppx_9mo_fractional_protection.png",
    "nhsn_fig5_infant_ppx_9mo_fractional_protection.pdf",
    "nssp_fig6_infant_ppx_realistic_delivery_fractional_protection.png",
    "nssp_fig6_infant_ppx_realistic_delivery_fractional_protection.pdf",
    "nhsn_fig6_infant_ppx_realistic_delivery_fractional_protection.png",
    "nhsn_fig6_infant_ppx_realistic_delivery_fractional_protection.pdf",
    "nssp_fig7_infant_ppx_realistic_delivery_8mo_censor_fractional_protection.png",
    "nssp_fig7_infant_ppx_realistic_delivery_8mo_censor_fractional_protection.pdf",
    "nhsn_fig7_infant_ppx_realistic_delivery_8mo_censor_fractional_protection.png",
    "nhsn_fig7_infant_ppx_realistic_delivery_8mo_censor_fractional_protection.pdf",
    "nssp_fig6_infant_ppx_efficacy_weighted_fractional_protection.png",
    "nssp_fig6_infant_ppx_efficacy_weighted_fractional_protection.pdf",
    "nhsn_fig6_infant_ppx_efficacy_weighted_fractional_protection.png",
    "nhsn_fig6_infant_ppx_efficacy_weighted_fractional_protection.pdf",
    "nssp_fig7_infant_ppx_8mo_censor_fractional_protection.png",
    "nssp_fig7_infant_ppx_8mo_censor_fractional_protection.pdf",
    "nhsn_fig7_infant_ppx_8mo_censor_fractional_protection.png",
    "nhsn_fig7_infant_ppx_8mo_censor_fractional_protection.pdf",
    "fig5_infant_ppx_stress_test_window_gains.png",
    "fig5_infant_ppx_stress_test_window_gains.pdf",
    "combined_fig5_infant_ppx_stress_test_window_gains.png",
    "combined_fig5_infant_ppx_stress_test_window_gains.pdf",
    "nssp_infant_ppx_hospitalizations_averted_early_vs_baseline.png",
    "nssp_infant_ppx_hospitalizations_averted_early_vs_baseline.pdf",
    "nssp_infant_ppx_hospitalizations_averted_late_vs_baseline.png",
    "nssp_infant_ppx_hospitalizations_averted_late_vs_baseline.pdf",
    "nssp_infant_ppx_hospitalizations_averted_extended_vs_baseline.png",
    "nssp_infant_ppx_hospitalizations_averted_extended_vs_baseline.pdf"
  )

  if (!write_regional_plots) {
    stale <- c(
      stale,
      "nssp_fig_supp_regional_choropleth.png",
      "nssp_fig_supp_regional_choropleth.pdf",
      "nhsn_fig_supp_regional_choropleth.png",
      "nhsn_fig_supp_regional_choropleth.pdf",
      "nssp_fig_supp_regional_ridgeline.png",
      "nssp_fig_supp_regional_ridgeline.pdf",
      "nhsn_fig_supp_regional_ridgeline.png",
      "nhsn_fig_supp_regional_ridgeline.pdf"
    )
  }

  unlink(file.path(fig_dir, stale))
}

# =============================================================================
# UTILITY
# =============================================================================

default_or <- function(value, fallback) {
  if (is.null(value)) return(fallback)
  if (is.character(value) && length(value) == 1 && (is.na(value) || value == ""))
    return(fallback)
  value
}

wrap_title <- function(value, width = 62) {
  str_wrap(value, width = width)
}

normalize_state_names <- function(x) {
  x <- str_to_title(x)
  x <- str_replace_all(x, " Of ", " of ")
  x <- str_replace_all(x, " And ", " and ")
  x <- ifelse(x == "District Of Columbia", "District of Columbia", x)
  x
}

outside_fraction_label <- function(metric_label, prefix = "Fraction") {
  base <- if (!is.null(metric_label) && !is.na(metric_label) && metric_label != "") {
    metric_label
  } else {
    "RSV activity"
  }
  if (str_detect(tolower(prefix), "median"))
    return(sprintf("Median fraction of %s outside window", base))
  sprintf("Fraction of %s outside window", base)
}

save_plot <- function(plot, filename, width = 10, height = 6) {
  ggsave(file.path(fig_dir, paste0(filename, ".png")),
         plot = plot, width = width, height = height, dpi = 300)
  ggsave(file.path(fig_dir, paste0(filename, ".pdf")),
         plot = plot, width = width, height = height, dpi = 300)
  invisible(plot)
}

# =============================================================================
# CONFIGURATION
# =============================================================================

labels        <- default_or(config$labels, list())
nssp_ts_label <- default_or(labels$nssp_timeseries, "RSV ED visit %")
nhsn_ts_label <- default_or(labels$nhsn_timeseries, "RSV-associated hospital admissions")
nssp_frac_lbl <- default_or(labels$nssp_fraction,   nssp_ts_label)
nhsn_frac_lbl <- default_or(labels$nhsn_fraction,   nhsn_ts_label)
fixed_window  <- config$fixed_window

state_abbrev <- tibble(
  jurisdiction = c(state.name, "District of Columbia"),
  state_abbrev = c(state.abb, "DC")
)

# Season colour palette (consistent across all figures)
season_colours <- c(
  "2023-2024" = "#4C78A8",
  "2024-2025" = "#F58518",
  "2025-2026" = "#54A24B"
)

# =============================================================================
# DATA LOADING
# =============================================================================

read_table <- function(name) {
  path <- file.path(root, "results", "tables", paste0(name, ".csv"))
  if (!file.exists(path)) stop(paste("Required table not found:", path))
  read_csv(path, show_col_types = FALSE)
}

maybe_table <- function(name) {
  path <- file.path(root, "results", "tables", paste0(name, ".csv"))
  if (!file.exists(path)) return(NULL)
  read_csv(path, show_col_types = FALSE)
}

read_processed <- function(prefix) {
  csv <- file.path(root, "data", "processed", paste0(prefix, "_processed.csv"))
  pq  <- file.path(root, "data", "processed", paste0(prefix, "_processed.parquet"))
  if (file.exists(csv)) return(read_csv(csv, show_col_types = FALSE))
  if (file.exists(pq) && has_arrow) return(arrow::read_parquet(pq))
  stop(paste("Processed data not found for", prefix))
}

get_states_sf <- function() {
  if (!has_maps || !has_sf) {
    message("Skipping choropleth: 'maps' or 'sf' not installed.")
    return(NULL)
  }
  mp <- maps::map("state", plot = FALSE, fill = TRUE)
  sf_obj <- sf::st_as_sf(mp) |>
    mutate(jurisdiction = normalize_state_names(ID))
  geom_col <- attr(sf_obj, "sf_column")
  if (!identical(geom_col, "geometry")) {
    names(sf_obj)[names(sf_obj) == geom_col] <- "geometry"
    attr(sf_obj, "sf_column") <- "geometry"
  }
  sf_obj
}

# =============================================================================
# THEME
# =============================================================================

base_theme <- function() {
  if (has_cowplot) cowplot::theme_minimal_grid() else theme_minimal()
}

choropleth_theme <- function() {
  theme_void() +
    theme(
      legend.position = "bottom",
      strip.text       = element_text(size = 10, face = "bold"),
      legend.title     = element_text(size = 8),
      legend.text      = element_text(size = 7)
    )
}

# =============================================================================
# FIGURE 1: Choropleth grid
# =============================================================================
# Sources are rows and seasons are columns so the NHSN panels align with the
# corresponding NSSP year. Source-season combinations with no data (e.g. NHSN
# 2023-24) render as a blank white panel.

plot_choropleth_grid <- function(nssp_outside, nhsn_outside, nssp_label, nhsn_label) {
  states_sf <- get_states_sf()
  if (is.null(states_sf)) {
    message("Skipping choropleth grid — sf/maps unavailable.")
    return(invisible(NULL))
  }

  # All seasons present in either source, in chronological order
  all_seasons <- sort(union(
    unique(nssp_outside$season[!is.na(nssp_outside$season)]),
    unique(nhsn_outside$season[!is.na(nhsn_outside$season)])
  ))

  # Tag each dataset with source, normalise jurisdiction names
  nssp_tagged <- nssp_outside |>
    filter(!is.na(season)) |>
    mutate(jurisdiction = normalize_state_names(jurisdiction), source = "NSSP")

  nhsn_tagged <- nhsn_outside |>
    filter(!is.na(season)) |>
    mutate(jurisdiction = normalize_state_names(jurisdiction), source = "NHSN")

  combined <- bind_rows(nssp_tagged, nhsn_tagged) |>
    mutate(
      season = factor(season, levels = all_seasons),
      source = factor(source, levels = c("NSSP", "NHSN"))
    )

  available_panels <- combined |>
    filter(!is.na(outside_fraction)) |>
    distinct(source, season)

  n_seasons <- length(all_seasons)
  panel_combos <- expand_grid(
    source = factor(c("NSSP", "NHSN"), levels = c("NSSP", "NHSN")),
    season = factor(all_seasons, levels = all_seasons)
  ) |>
    semi_join(available_panels, by = c("source", "season"))

  states_rep <- states_sf[rep(seq_len(nrow(states_sf)), each = nrow(panel_combos)), ]
  states_rep <- bind_cols(
    states_rep,
    panel_combos[rep(seq_len(nrow(panel_combos)), times = nrow(states_sf)), ]
  )

  joined <- states_rep |>
    left_join(
      combined |> select(jurisdiction, source, season, outside_fraction),
      by = c("jurisdiction", "source", "season")
    )

  vmax <- min(quantile(combined$outside_fraction, 0.95, na.rm = TRUE), 0.25)

  p <- ggplot(joined) +
    geom_sf(aes(fill = outside_fraction), color = "gray70", linewidth = 0.15) +
    coord_sf(crs = "ESRI:102003", datum = NA) +
    facet_grid(source ~ season, drop = FALSE) +
    scale_fill_gradient(
      low = "#fee5d9", high = "#a50f15",
      limits = c(0, vmax), oob = scales::squish, na.value = "lightgray",
      name = "Out-of-window fraction",
      guide = guide_colorbar(
        title.position = "top", title.hjust = 0.5,
        barwidth = unit(12, "lines"), barheight = unit(0.6, "lines")
      )
    ) +
    choropleth_theme()

  # Panel dimensions: columns = seasons, rows = 2 sources.
  states_proj <- sf::st_transform(states_sf, "ESRI:102003")
  bbox <- sf::st_bbox(states_proj)
  ar <- as.numeric((bbox["xmax"] - bbox["xmin"]) / (bbox["ymax"] - bbox["ymin"]))
  ncols <- n_seasons
  nrows <- 2
  w <- 5 * ncols
  h <- 5 / ar * nrows + 1.5

  save_plot(p, "fig1_choropleth_grid", width = w, height = h)
  invisible(p)
}

# =============================================================================
# FIGURE 2: Ridgeline density plots
# =============================================================================

# Layout A — seasons as ridgelines, one facet per NHSN age group.
# An additional single-panel plot is made for NSSP (all-ages only).
plot_ridgeline_seasons_by_agegroup <- function(nhsn_strata_df, nssp_outside) {
  if (!has_ridges) {
    message("Skipping ridgeline plots — ggridges not installed.")
    return(invisible(NULL))
  }
  library(ggridges)

  # ------ NHSN: faceted by age group, seasons as ridges ------
  if (!is.null(nhsn_strata_df) && nrow(nhsn_strata_df) > 0 &&
      "age_group_label" %in% names(nhsn_strata_df)) {

    df <- nhsn_strata_df |>
      filter(!is.na(season), !is.na(outside_fraction)) |>
      mutate(
        pct = outside_fraction * 100,
        season = factor(season, levels = rev(sort(unique(season))))
      )

    p_nhsn <- ggplot(df, aes(x = pct, y = season, fill = season)) +
      stat_density_ridges(
        quantile_lines = TRUE, quantiles = 2,
        alpha = 0.8, bandwidth = 1.5,
        jittered_points = TRUE,
        point_shape = "|", point_size = 1.5, point_alpha = 0.6,
        position = position_points_jitter(height = 0)
      ) +
      scale_fill_manual(values = season_colours, guide = "none") +
      facet_wrap(~age_group_label, scales = "free_y") +
      labs(
        x = "Out-of-window RSV activity (%)",
        y = NULL,
        title = wrap_title("Distribution of out-of-window RSV fractions by age group (NHSN)")
      ) +
      scale_x_continuous(limits = c(0, NA)) +
      theme_minimal() +
      theme(
        strip.text = element_text(size = 9, face = "bold"),
        plot.title = element_text(size = 11, face = "bold", lineheight = 1.05, margin = margin(b = 8)),
        axis.text  = element_text(size = 8),
        panel.grid.minor = element_blank()
      )

    n_age_groups <- n_distinct(df$age_group_label)
    save_plot(p_nhsn, "fig2_ridgeline_nhsn_seasons_by_agegroup",
              width = 5 * min(n_age_groups, 3), height = 5)
  }

  # ------ NSSP: single panel, seasons as ridges ------
  if (!is.null(nssp_outside) && nrow(nssp_outside) > 0) {
    df_nssp <- nssp_outside |>
      filter(!is.na(season), !is.na(outside_fraction)) |>
      mutate(
        pct    = outside_fraction * 100,
        season = factor(season, levels = rev(sort(unique(season))))
      )

    p_nssp <- ggplot(df_nssp, aes(x = pct, y = season, fill = season)) +
      stat_density_ridges(
        quantile_lines = TRUE, quantiles = 2,
        alpha = 0.8, bandwidth = 1.5,
        jittered_points = TRUE,
        point_shape = "|", point_size = 1.5, point_alpha = 0.6,
        position = position_points_jitter(height = 0)
      ) +
      scale_fill_manual(values = season_colours, guide = "none") +
      labs(
        x = "Out-of-window RSV activity (%)",
        y = NULL
      ) +
      scale_x_continuous(limits = c(0, NA)) +
      theme_minimal() +
      theme(
        axis.text = element_text(size = 9),
        panel.grid.minor = element_blank()
      )

    save_plot(p_nssp, "fig2_ridgeline_nssp_seasons", width = 6, height = 4)
  }
}

# Layout B — age groups as ridgelines, faceted by season.
plot_ridgeline_agegroups_by_season <- function(nhsn_strata_df) {
  if (!has_ridges || is.null(nhsn_strata_df) || nrow(nhsn_strata_df) == 0) {
    return(invisible(NULL))
  }
  library(ggridges)

  if (!"age_group_label" %in% names(nhsn_strata_df)) return(invisible(NULL))

  df <- nhsn_strata_df |>
    filter(!is.na(season), !is.na(outside_fraction)) |>
    mutate(
      pct = outside_fraction * 100,
      age_group_label = factor(age_group_label,
                               levels = rev(unique(age_group_label)))
    )

  p <- ggplot(df, aes(x = pct, y = age_group_label, fill = age_group_label)) +
    stat_density_ridges(
      quantile_lines = TRUE, quantiles = 2,
      alpha = 0.8, bandwidth = 1.5,
      jittered_points = TRUE,
      point_shape = "|", point_size = 1.5, point_alpha = 0.6,
      position = position_points_jitter(height = 0)
    ) +
    scale_fill_brewer(palette = "Set2", guide = "none") +
    facet_wrap(~season) +
    labs(
      x = "Out-of-window RSV activity (%)",
      y = NULL,
      title = wrap_title("NHSN: out-of-window RSV fractions by age group and season")
    ) +
    scale_x_continuous(limits = c(0, NA)) +
    theme_minimal() +
    theme(
      strip.text = element_text(size = 9, face = "bold"),
      plot.title = element_text(size = 11, face = "bold", lineheight = 1.05, margin = margin(b = 8)),
      axis.text  = element_text(size = 8),
      panel.grid.minor = element_blank()
    )

  n_seasons <- n_distinct(df$season)
  save_plot(p, "fig2_ridgeline_nhsn_agegroups_by_season",
            width = 5 * min(n_seasons, 3), height = 4)
  invisible(p)
}

# =============================================================================
# FIGURE 3: Coverage comparison — violin + jitter + CI
# =============================================================================
# X-axis: window definitions ordered narrowest → widest.
# Each season/window violin shows the state-level coverage distribution. Jittered
# points are states; black points and intervals show the median and bootstrap
# 95% CI, or IQR fallback if bootstrap results are unavailable.

plot_coverage_comparison_with_ci <- function(
    extended_df, bootstrap_ci_df, prefix,
    source_label = "NSSP"
) {
  # Ordered window labels (narrowest → widest)
  window_order <- c("Baseline\nOct–Mar", "Early\nSep–Mar",
                    "Late\nOct–Apr", "Extended\nSep–Apr")

  metric_to_window <- c(
    median_coverage_baseline_oct_mar = "Baseline\nOct–Mar",
    median_coverage_early_sep_mar    = "Early\nSep–Mar",
    median_coverage_late_oct_apr     = "Late\nOct–Apr",
    median_coverage_extended_sep_apr = "Extended\nSep–Apr"
  )
  window_name_to_label <- c(
    baseline_oct_mar = "Baseline\nOct–Mar",
    early_sep_mar    = "Early\nSep–Mar",
    late_oct_apr     = "Late\nOct–Apr",
    extended_sep_apr = "Extended\nSep–Apr"
  )

  # --- Assemble state-level coverage values ---
  ext_values <- extended_df |>
    filter(!is.na(coverage)) |>
    mutate(window = window_name_to_label[window_name]) |>
    filter(!is.na(window)) |>
    select(season, jurisdiction, window, coverage)

  values_df <- ext_values |>
    mutate(
      window = factor(window, levels = window_order),
      season = factor(season, levels = sort(unique(season)))
    )

  # --- Assemble point estimates and intervals ---
  ext_summary <- values_df |>
    group_by(season, window) |>
    summarise(
      point = median(coverage, na.rm = TRUE),
      q25   = quantile(coverage, 0.25, na.rm = TRUE),
      q75   = quantile(coverage, 0.75, na.rm = TRUE),
      .groups = "drop"
    )

  df <- ext_summary |> select(season, window, point, q25, q75)

  # --- Substitute bootstrap CIs where available ---
  if (!is.null(bootstrap_ci_df) && nrow(bootstrap_ci_df) > 0) {
    ci_wide <- bootstrap_ci_df |>
      filter(metric %in% names(metric_to_window)) |>
      mutate(window = metric_to_window[metric]) |>
      select(season, window, ci_lower, ci_upper)

    df <- df |>
      left_join(ci_wide, by = c("season", "window")) |>
      mutate(
        lo = coalesce(ci_lower, q25),
        hi = coalesce(ci_upper, q75)
      )
  } else {
    df <- df |> mutate(lo = q25, hi = q75)
  }

  df <- df |>
    mutate(
      window = factor(window, levels = window_order),
      season = factor(season, levels = sort(unique(season)))
    )

  values_df <- values_df |>
    filter(!is.na(window), !is.na(season), !is.na(coverage))

  y_lo <- floor(min(values_df$coverage, df$lo, na.rm = TRUE) * 20) / 20
  y_hi <- 1.0

  dodge <- position_dodge(width = 0.78)

  p <- ggplot(values_df, aes(x = window, y = coverage, fill = season)) +
    geom_violin(
      aes(group = interaction(window, season)),
      alpha = 0.22, color = NA, scale = "width", trim = FALSE,
      position = dodge
    ) +
    geom_point(
      aes(color = season, group = season),
      position = position_jitterdodge(jitter.width = 0.12, dodge.width = 0.78),
      size = 1.4, alpha = 0.35, stroke = 0
    ) +
    geom_errorbar(
      data = df,
      aes(x = window, ymin = lo, ymax = hi, group = season),
      inherit.aes = FALSE,
      width = 0.12, color = "black", linewidth = 0.45,
      position = dodge
    ) +
    geom_point(
      data = df,
      aes(x = window, y = point, group = season),
      inherit.aes = FALSE,
      color = "black", fill = "white", shape = 21, size = 2.2,
      position = dodge
    ) +
    scale_color_manual(values = season_colours, name = "Season",
                       guide = guide_legend(override.aes = list(alpha = 1, size = 2.5))) +
    scale_fill_manual(values  = season_colours, guide = "none") +
    scale_y_continuous(
      breaks = seq(0, 1, 0.05),
      labels = scales::percent_format(accuracy = 1),
      expand = expansion(mult = c(0.02, 0.02))
    ) +
    coord_cartesian(ylim = c(y_lo, y_hi)) +
    labs(
      x     = NULL,
      y     = "State coverage (% of RSV burden captured)",
      title = wrap_title(paste0(source_label,
                     ": coverage by window definition"))
    ) +
    theme_minimal(base_size = 11) +
    theme(
      panel.grid.major.x = element_blank(),
      panel.grid.minor   = element_blank(),
      strip.text         = element_text(size = 9, face = "bold"),
      plot.title         = element_text(size = 11, face = "bold", lineheight = 1.05, margin = margin(b = 8)),
      axis.text.x        = element_text(size = 9),
      axis.text.y        = element_text(size = 9),
      axis.title.y       = element_text(size = 9, margin = margin(r = 8)),
      legend.position    = "bottom",
      legend.title       = element_text(size = 9),
      legend.text        = element_text(size = 9)
    )

  save_plot(p, paste0(prefix, "fig3_coverage_with_ci"), width = 7, height = 5)
  invisible(p)
}

# =============================================================================
# SUPPLEMENTARY: State-level time series
# =============================================================================

plot_infant_ppx_fractional_protection <- function(
    summary_df, prefix, source_label = "NSSP",
    figure_stub = "fig3_infant_ppx_realistic_delivery_fractional_protection",
    title_suffix = "",
    y_max = 1.0
) {
  if (is.null(summary_df) || nrow(summary_df) == 0) return(invisible(NULL))

  window_order <- c("Baseline\nOct–Mar", "Early\nSep–Mar",
                    "Late\nOct–Apr", "Extended\nSep–Apr")
  window_name_to_label <- c(
    baseline_oct_mar = "Baseline\nOct–Mar",
    early_sep_mar    = "Early\nSep–Mar",
    late_oct_apr     = "Late\nOct–Apr",
    extended_sep_apr = "Extended\nSep–Apr"
  )

  values_df <- summary_df |>
    mutate(
      window = window_name_to_label[window_name],
      season = factor(season, levels = sort(unique(season))),
      person_protection = median_person_activity_fractional_protection
    ) |>
    filter(!is.na(window), !is.na(season), !is.na(person_protection)) |>
    mutate(window = factor(window, levels = window_order))

  if (nrow(values_df) == 0) return(invisible(NULL))

  summary_points <- values_df |>
    group_by(season, window) |>
    summarise(
      point = median(person_protection, na.rm = TRUE),
      q25 = quantile(person_protection, 0.25, na.rm = TRUE),
      q75 = quantile(person_protection, 0.75, na.rm = TRUE),
      .groups = "drop"
    )

  dodge <- position_dodge(width = 0.78)

  p <- ggplot(values_df, aes(x = window, y = person_protection, fill = season)) +
    geom_violin(
      aes(group = interaction(window, season)),
      alpha = 0.22, color = NA, scale = "width", trim = FALSE,
      position = dodge
    ) +
    geom_point(
      aes(color = season, group = season),
      position = position_jitterdodge(jitter.width = 0.12, dodge.width = 0.78),
      size = 1.4, alpha = 0.35, stroke = 0
    ) +
    geom_errorbar(
      data = summary_points,
      aes(x = window, ymin = q25, ymax = q75, group = season),
      inherit.aes = FALSE,
      width = 0.12, color = "black", linewidth = 0.45,
      position = dodge
    ) +
    geom_point(
      data = summary_points,
      aes(x = window, y = point, group = season),
      inherit.aes = FALSE,
      color = "black", fill = "white", shape = 21, size = 2.2,
      position = dodge
    ) +
    scale_color_manual(values = season_colours, name = "Season",
                       guide = guide_legend(override.aes = list(alpha = 1, size = 2.5))) +
    scale_fill_manual(values = season_colours, guide = "none") +
    scale_y_continuous(
      breaks = seq(0, y_max, 0.05),
      labels = scales::percent_format(accuracy = 1),
      expand = expansion(mult = c(0.02, 0.02))
    ) +
    coord_cartesian(ylim = c(0, y_max)) +
    labs(
      x = NULL,
      y = "Median person-level fractional protection"
    ) +
    theme_minimal(base_size = 11) +
    theme(
      panel.grid.major.x = element_blank(),
      panel.grid.minor = element_blank(),
      axis.text.x = element_text(size = 9),
      axis.text.y = element_text(size = 9),
      axis.title.y = element_text(size = 9, margin = margin(r = 8)),
      legend.position = "bottom",
      legend.title = element_text(size = 9),
      legend.text = element_text(size = 9)
    )

  save_plot(p, paste0(prefix, figure_stub), width = 7, height = 5)
  invisible(p)
}

plot_infant_ppx_stress_test <- function(state_summary) {
  if (is.null(state_summary) || nrow(state_summary) == 0) return(invisible(NULL))

  window_labels <- c(
    early_sep_mar = "Early (Sep-Mar)",
    late_oct_apr = "Late (Oct-Apr)",
    extended_sep_apr = "Extended (Sep-Apr)"
  )
  df <- state_summary |>
    filter(datasource == "nssp") |>
    filter(!str_detect(scenario_id, "^efficacy_binary_")) |>
    filter(window_name %in% c("baseline_oct_mar", names(window_labels))) |>
    select(
      datasource, season, jurisdiction, scenario_id, scenario_order,
      scenario_label, window_name, median_person_activity_fractional_protection
    ) |>
    pivot_wider(
      names_from = window_name,
      values_from = median_person_activity_fractional_protection
    ) |>
    pivot_longer(
      cols = all_of(names(window_labels)),
      names_to = "window_name",
      values_to = "person_protection"
    ) |>
    filter(!is.na(baseline_oct_mar), !is.na(person_protection)) |>
    mutate(
      window = recode(window_name, !!!window_labels),
      window = factor(window, levels = rev(unname(window_labels))),
      scenario_label = str_wrap(scenario_label, width = 44),
      scenario_label = fct_reorder(scenario_label, scenario_order, .fun = min),
      scenario_label = fct_rev(scenario_label),
      delta_pp = (person_protection - baseline_oct_mar) * 100
    )

  if (nrow(df) == 0) return(invisible(NULL))

  p <- ggplot(df, aes(x = delta_pp, y = scenario_label, fill = window)) +
    geom_vline(xintercept = 0, linewidth = 0.4, color = "grey55") +
    geom_boxplot(
      aes(group = interaction(scenario_label, window)),
      position = position_dodge2(width = 0.72, preserve = "single"),
      width = 0.52,
      alpha = 0.75,
      outlier.shape = NA,
      outlier.size = 0.7,
      linewidth = 0.35
    ) +
    scale_fill_manual(
      values = c(
        "Early (Sep-Mar)" = "#1b9e77",
        "Late (Oct-Apr)" = "#d95f02",
        "Extended (Sep-Apr)" = "#7570b3"
      ),
      breaks = unname(window_labels),
      name = NULL,
      guide = guide_legend(
        override.aes = list(shape = 22, size = 4, linetype = 0, alpha = 1)
      )
    ) +
    labs(
      x = "Change vs Oct-Mar baseline (percentage points)",
      y = NULL
    ) +
    theme_minimal(base_size = 11) +
    theme(
      panel.grid.major.y = element_blank(),
      panel.grid.minor = element_blank(),
      strip.text = element_text(size = 9, face = "bold"),
      axis.text.x = element_text(size = 9),
      axis.text.y = element_text(size = 8),
      legend.position = c(0.98, 0.98),
      legend.justification = c(1, 1),
      legend.background = element_rect(fill = "white", color = "grey85", linewidth = 0.2),
      legend.text = element_text(size = 9)
    )

  save_plot(p, "combined_infant_ppx_stress_test_window_gains", width = 9, height = 5.8)
  invisible(p)
}

plot_infant_hospitalizations_averted <- function(
    hosp_df,
    figure_stub = "nssp_infant_ppx_hospitalizations_averted_early_vs_baseline"
) {
  if (is.null(hosp_df) || nrow(hosp_df) == 0) return(invisible(NULL))

  values_df <- hosp_df |>
    filter(
      datasource == "nssp",
      !is.na(season),
      !is.na(coalesce(hospitalizations_averted_vs_baseline, hospitalizations_averted_early_vs_baseline))
    ) |>
    mutate(
      season = factor(season, levels = sort(unique(season))),
      hospitalizations_averted = coalesce(
        hospitalizations_averted_vs_baseline,
        hospitalizations_averted_early_vs_baseline
      )
    )

  if (nrow(values_df) == 0) return(invisible(NULL))

  summary_points <- values_df |>
    group_by(season) |>
    summarise(
      point = median(hospitalizations_averted, na.rm = TRUE),
      q25 = quantile(hospitalizations_averted, 0.25, na.rm = TRUE),
      q75 = quantile(hospitalizations_averted, 0.75, na.rm = TRUE),
      .groups = "drop"
    )

  comparison_label <- if ("comparison_window_label" %in% names(values_df)) {
    values_df |>
      distinct(comparison_window_label) |>
      pull(comparison_window_label) |>
      first()
  } else {
    "Early Sep-Mar"
  }
  comparison_label <- default_or(comparison_label, "Alternative")

  y_lower <- -100
  y_upper <- max(values_df$hospitalizations_averted, summary_points$q75, na.rm = TRUE)
  y_upper <- ceiling(y_upper / 5) * 5
  if (!is.finite(y_lower)) y_lower <- 0
  if (!is.finite(y_upper) || y_upper <= y_lower) y_upper <- NA_real_

  p <- ggplot(values_df, aes(x = season, y = hospitalizations_averted)) +
    geom_violin(
      fill = "#9CA3AF", alpha = 0.26, color = NA, scale = "width", trim = FALSE
    ) +
    geom_point(
      position = position_jitter(width = 0.12, height = 0),
      color = "#6B7280", size = 1.5, alpha = 0.48, stroke = 0
    ) +
    geom_errorbar(
      data = summary_points,
      aes(x = season, ymin = q25, ymax = q75),
      inherit.aes = FALSE,
      width = 0.12, color = "black", linewidth = 0.45
    ) +
    geom_point(
      data = summary_points,
      aes(x = season, y = point),
      inherit.aes = FALSE,
      color = "black", fill = "white", shape = 21, size = 2.2
    ) +
    scale_y_continuous(
      breaks = scales::pretty_breaks(n = 6),
      expand = expansion(mult = c(0.02, 0.04))
    ) +
    coord_cartesian(ylim = c(y_lower, y_upper)) +
    labs(
      x = NULL,
      y = "Expected RSV hospitalizations averted per state"
    ) +
    theme_minimal(base_size = 11) +
    theme(
      panel.grid.major.x = element_blank(),
      panel.grid.minor = element_blank(),
      axis.text.x = element_text(size = 9),
      axis.text.y = element_text(size = 9),
      axis.title.y = element_text(size = 9, margin = margin(r = 8))
    )

  save_plot(p, figure_stub, width = 6.5, height = 5)
  invisible(p)
}

plot_timeseries <- function(df, metric_label, prefix, value_col, free_y = FALSE) {
  df <- df |>
    mutate(week_end = as.Date(week_end)) |>
    filter(!is.na(.data[[value_col]]), !is.na(season))

  if (!"state_abbrev" %in% names(df))
    df <- df |> left_join(state_abbrev, by = "jurisdiction")
  df <- df |> mutate(facet_label = coalesce(state_abbrev, jurisdiction))

  season_windows <- df |>
    distinct(season) |>
    mutate(
      start_year   = as.integer(str_split(season, "-", simplify = TRUE)[, 1]),
      end_year     = as.integer(str_split(season, "-", simplify = TRUE)[, 2]),
      window_start = as.Date(sprintf("%d-%02d-%02d", start_year,
                                    fixed_window$start_month, fixed_window$start_day)),
      window_end   = as.Date(sprintf("%d-%02d-%02d", end_year,
                                    fixed_window$end_month, fixed_window$end_day))
    )

  p <- ggplot(df, aes(x = week_end, y = .data[[value_col]], color = season)) +
    geom_rect(
      inherit.aes = FALSE, data = season_windows,
      aes(xmin = window_start, xmax = window_end, ymin = -Inf, ymax = Inf),
      fill = "green", alpha = 0.15
    ) +
    geom_line(linewidth = 0.4) +
    scale_color_manual(values = season_colours) +
    facet_wrap(~facet_label, ncol = 6,
               scales = if (free_y) "free_y" else "fixed") +
    labs(x = "Week", y = metric_label, color = "Season") +
    theme_minimal() +
    theme(
      strip.text   = element_text(size = 7),
      axis.text.x  = element_text(size = 9, angle = 90, hjust = 1, vjust = 0.5),
      axis.text.y  = element_text(size = 9),
      legend.position = "bottom",
      panel.grid.minor = element_blank()
    )

  save_plot(p, paste0(prefix, "fig_supp_timeseries"), width = 18, height = 10)
  invisible(p)
}

# =============================================================================
# SUPPLEMENTARY: Regional summaries
# =============================================================================

plot_regional_choropleth <- function(outside_df, metric_label, prefix) {
  states_sf <- get_states_sf()
  if (is.null(states_sf)) return(invisible(NULL))

  region_df <- tibble(
    jurisdiction = unlist(config$hhs_regions),
    hhs_region   = as.integer(rep(names(config$hhs_regions),
                                  lengths(config$hhs_regions)))
  )

  regional_medians <- outside_df |>
    filter(!is.na(season)) |>
    mutate(jurisdiction = normalize_state_names(jurisdiction)) |>
    left_join(region_df, by = "jurisdiction") |>
    group_by(season, hhs_region) |>
    summarise(median_outside_fraction = median(outside_fraction, na.rm = TRUE),
              .groups = "drop")

  seasons_list <- sort(unique(regional_medians$season))
  states_regions <- states_sf |>
    left_join(region_df, by = "jurisdiction") |>
    filter(!is.na(hhs_region))

  states_rep <- do.call(rbind, lapply(seasons_list, function(s)
    states_regions |> mutate(season = s)))
  states_rep <- states_rep |>
    left_join(regional_medians, by = c("hhs_region", "season")) |>
    sf::st_as_sf()

  old_s2 <- sf::sf_use_s2(FALSE)
  on.exit(sf::sf_use_s2(old_s2), add = TRUE)

  joined <- states_rep |>
    sf::st_make_valid() |>
    group_by(season, hhs_region, median_outside_fraction) |>
    summarise(.groups = "drop")

  vmax <- min(max(joined$median_outside_fraction, na.rm = TRUE) * 1.1, 0.20)

  p <- ggplot(joined) +
    geom_sf(aes(fill = median_outside_fraction), color = "black", linewidth = 0.3) +
    coord_sf(crs = "ESRI:102003", datum = NA) +
    facet_wrap(~season) +
    scale_fill_gradient(
      low = "#fee5d9", high = "#a50f15",
      limits = c(0, vmax), oob = scales::squish, na.value = "lightgray",
      name = outside_fraction_label(metric_label, "Median"),
      guide = guide_colorbar(
        title.position = "top", title.hjust = 0.5,
        barwidth = unit(12, "lines"), barheight = unit(0.6, "lines")
      )
    ) +
    choropleth_theme()

  states_proj <- sf::st_transform(states_sf, "ESRI:102003")
  bbox <- sf::st_bbox(states_proj)
  ar   <- as.numeric((bbox["xmax"] - bbox["xmin"]) / (bbox["ymax"] - bbox["ymin"]))
  ncols <- n_distinct(joined$season)
  save_plot(p, paste0(prefix, "fig_supp_regional_choropleth"),
            width = 5 * ncols, height = 5 / ar + 0.8)
}

plot_regional_ridgeline <- function(outside_df, metric_label, prefix) {
  if (!has_ridges) return(invisible(NULL))
  library(ggridges)

  region_df <- tibble(
    jurisdiction = unlist(config$hhs_regions),
    hhs_region   = as.integer(rep(names(config$hhs_regions),
                                  lengths(config$hhs_regions))),
    region_label = paste0("Region ", as.integer(
      rep(names(config$hhs_regions), lengths(config$hhs_regions))
    ))
  )

  df <- outside_df |>
    filter(!is.na(season), !is.na(outside_fraction)) |>
    mutate(jurisdiction = normalize_state_names(jurisdiction)) |>
    left_join(region_df, by = "jurisdiction") |>
    filter(!is.na(hhs_region)) |>
    mutate(
      pct          = outside_fraction * 100,
      region_label = factor(region_label, levels = paste("Region", 10:1)),
      season       = factor(season, levels = sort(unique(season)))
    )

  p <- ggplot(df, aes(x = pct, y = region_label, fill = season)) +
    stat_density_ridges(alpha = 0.7, bandwidth = 1.5, quantile_lines = TRUE,
                        quantiles = 2) +
    scale_fill_manual(values = season_colours) +
    facet_wrap(~season) +
    labs(x = "Out-of-window fraction (%)", y = NULL,
         fill = "Season",
         title = wrap_title(paste0(prefix |> str_remove("_$"), ": regional distribution"))) +
    scale_x_continuous(limits = c(0, NA)) +
    theme_minimal() +
    theme(strip.text = element_text(size = 9), axis.text = element_text(size = 8),
          plot.title = element_text(size = 11, face = "bold", lineheight = 1.05, margin = margin(b = 8)),
          panel.grid.minor = element_blank(), legend.position = "none")

  n_seasons <- n_distinct(df$season)
  save_plot(p, paste0(prefix, "fig_supp_regional_ridgeline"),
            width = 4 * min(n_seasons, 3) + 1, height = 5)
  invisible(p)
}

# =============================================================================
# MAIN
# =============================================================================

nssp_outside  <- read_table("nssp_outside_fraction_by_state")
nhsn_outside  <- read_table("nhsn_outside_fraction_by_state")
nssp_extended <- read_table("nssp_extended_windows_evaluation")
nhsn_extended <- read_table("nhsn_extended_windows_evaluation")
nssp_regional <- read_table("nssp_regional_summary")
nhsn_regional <- read_table("nhsn_regional_summary")

nssp_processed <- read_processed("nssp")
nhsn_processed <- read_processed("nhsn")

nssp_boot <- maybe_table("nssp_bootstrap_ci_summary")
nhsn_boot <- maybe_table("nhsn_bootstrap_ci_summary")
nhsn_strata <- maybe_table("nhsn_outside_fraction_all_strata")
nssp_infant_ppx_realistic12mo <- maybe_table("nssp_infant_ppx_realistic12mo_state_summary")
nhsn_infant_ppx_realistic12mo <- maybe_table("nhsn_infant_ppx_realistic12mo_state_summary")
nssp_infant_ppx_realistic8mo <- maybe_table("nssp_infant_ppx_realistic8mo_state_summary")
nhsn_infant_ppx_realistic8mo <- maybe_table("nhsn_infant_ppx_realistic8mo_state_summary")
infant_ppx_stress_summary <- maybe_table("infant_ppx_stress_test_window_summary")
infant_ppx_stress_state <- maybe_table("infant_ppx_stress_test_state_summary")
infant_hosp_averted <- maybe_table("infant_ppx_hospitalizations_averted_early_vs_baseline")
infant_hosp_averted_late <- maybe_table("infant_ppx_hospitalizations_averted_late_vs_baseline")
infant_hosp_averted_extended <- maybe_table("infant_ppx_hospitalizations_averted_extended_vs_baseline")

remove_stale_default_figures()

# Figure 1: Choropleth grid (all seasons, both sources)
plot_choropleth_grid(nssp_outside, nhsn_outside, nssp_frac_lbl, nhsn_frac_lbl)

# Figure 2: Ridgeline density plots
plot_ridgeline_seasons_by_agegroup(nhsn_strata, nssp_outside)
plot_ridgeline_agegroups_by_season(nhsn_strata)

# Figure 3: Infant prophylaxis model with realistic delivery priors
plot_infant_ppx_fractional_protection(
  nssp_infant_ppx_realistic12mo, "nssp_",
  source_label = "NSSP",
  figure_stub = "fig3_infant_ppx_realistic_delivery_fractional_protection",
  title_suffix = " (realistic delivery; 12-month censor)",
  y_max = 0.2
)
plot_infant_ppx_fractional_protection(
  nhsn_infant_ppx_realistic12mo, "nhsn_",
  source_label = "NHSN (ages 0–4)",
  figure_stub = "fig3_infant_ppx_realistic_delivery_fractional_protection",
  title_suffix = " (realistic delivery; 12-month censor)",
  y_max = 0.2
)

# Figure 4: Infant prophylaxis model with realistic delivery priors and 8-month censor
plot_infant_ppx_fractional_protection(
  nssp_infant_ppx_realistic8mo, "nssp_",
  source_label = "NSSP",
  figure_stub = "fig4_infant_ppx_realistic_delivery_8mo_censor_fractional_protection",
  title_suffix = " (realistic delivery; 8-month censor)",
  y_max = 0.2
)
plot_infant_ppx_fractional_protection(
  nhsn_infant_ppx_realistic8mo, "nhsn_",
  source_label = "NHSN (ages 0–4)",
  figure_stub = "fig4_infant_ppx_realistic_delivery_8mo_censor_fractional_protection",
  title_suffix = " (realistic delivery; 8-month censor)",
  y_max = 0.2
)

# Figure 5: Robustness of window gains across model assumptions
plot_infant_ppx_stress_test(infant_ppx_stress_state)

# Absolute hospitalization translation for the 100% uptake, otherwise-reference scenario
plot_infant_hospitalizations_averted(
  infant_hosp_averted,
  "nssp_infant_ppx_hospitalizations_averted_early_vs_baseline"
)
plot_infant_hospitalizations_averted(
  infant_hosp_averted_late,
  "nssp_infant_ppx_hospitalizations_averted_late_vs_baseline"
)
plot_infant_hospitalizations_averted(
  infant_hosp_averted_extended,
  "nssp_infant_ppx_hospitalizations_averted_extended_vs_baseline"
)

# Supplementary: Time series
plot_timeseries(nssp_processed, nssp_ts_label, "nssp_",
                default_or(config$primary_outcome, "rsv_pct"), free_y = FALSE)
plot_timeseries(nhsn_processed, nhsn_ts_label, "nhsn_",
                default_or(config$nhsn_primary_outcome, "rsv_ped_0_4"), free_y = TRUE)

if (write_regional_plots) {
  plot_regional_choropleth(nssp_outside, nssp_frac_lbl, "nssp_")
  plot_regional_choropleth(nhsn_outside, nhsn_frac_lbl, "nhsn_")
  plot_regional_ridgeline(nssp_outside, nssp_frac_lbl, "nssp_")
  plot_regional_ridgeline(nhsn_outside, nhsn_frac_lbl, "nhsn_")
}

message("All figures saved to ", fig_dir)

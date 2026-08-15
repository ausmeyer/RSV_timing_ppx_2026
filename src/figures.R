#!/usr/bin/env Rscript
#
# figures.R - RSV prophylaxis timing analysis
#
# Generates the publication figures:
#   Figure 1: choropleth grid of out-of-window RSV fraction
#   Figure 2: ridgeline densities by season and age group
#   Figure 3: window advantage over Oct-March baseline across stress-test scenarios
#   Figure 4: per-state hospitalizations averted by window (50% uptake)
#   Figure 5: national hospitalizations averted, primary model vs 50% uptake (panels A/B)
#   Supplementary: state-level time series
#

# =============================================================================
# SETUP
# =============================================================================

suppressPackageStartupMessages({
  library(tidyverse)
  library(yaml)
  library(lubridate)
})

has_ridges  <- requireNamespace("ggridges", quietly = TRUE)
has_arrow   <- requireNamespace("arrow",    quietly = TRUE)

root    <- getwd()
fig_dir <- file.path(root, "results", "figures")
dir.create(fig_dir, recursive = TRUE, showWarnings = FALSE)

config <- yaml::read_yaml(file.path(root, "config.yaml"))


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

read_processed <- function(prefix) {
  csv <- file.path(root, "data", "processed", paste0(prefix, "_processed.csv"))
  pq  <- file.path(root, "data", "processed", paste0(prefix, "_processed.parquet"))
  if (file.exists(csv)) return(read_csv(csv, show_col_types = FALSE))
  if (file.exists(pq) && has_arrow) return(arrow::read_parquet(pq))
  stop(paste("Processed data not found for", prefix))
}

rename_geometry <- function(sf_obj) {
  geom_col <- attr(sf_obj, "sf_column")
  if (!identical(geom_col, "geometry")) {
    names(sf_obj)[names(sf_obj) == geom_col] <- "geometry"
    attr(sf_obj, "sf_column") <- "geometry"
  }
  sf_obj
}

# State geometry for the choropleths is downloaded by `make data` and kept with
# the other ignored public inputs. Figure 1 requires all 50 states and DC.
get_states_sf <- function() {
  if (!requireNamespace("sf", quietly = TRUE)) stop("Required package missing: sf")

  keep <- c(state.name, "District of Columbia")
  geometry_cfg <- config$analysis_data$state_geometry
  if (is.null(geometry_cfg$filename)) {
    stop("analysis_data.state_geometry.filename is not configured")
  }
  geometry_path <- file.path(root, "data", "raw", geometry_cfg$filename)
  if (!file.exists(geometry_path)) {
    stop(paste("Required Census state geometry not found:", geometry_path,
               "Run `make data` first."))
  }

  states <- readRDS(geometry_path) |>
    filter(NAME %in% keep)
  missing_states <- setdiff(keep, states$NAME)
  if (nrow(states) != length(keep) || length(missing_states)) {
    stop(paste(
      "Census state geometry must contain exactly 50 states and DC; missing:",
      paste(missing_states, collapse = ", ")
    ))
  }

  states <- states |>
    mutate(jurisdiction = normalize_state_names(NAME))
  rename_geometry(states)
}

# =============================================================================
# THEME
# =============================================================================


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
    message("Skipping choropleth grid: sf/maps unavailable.")
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

  # Use the full observed range so high out-of-window states (up to ~43% in
  # 2025-2026) remain distinguishable rather than saturating at a hard cap.
  vmax <- max(combined$outside_fraction, na.rm = TRUE)

  p <- ggplot(joined) +
    geom_sf(aes(fill = outside_fraction), color = "gray70", linewidth = 0.15) +
    coord_sf(datum = NA) +
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

# Manuscript Figure 2: NSSP seasons as ridgelines.
plot_ridgeline_nssp <- function(nssp_outside) {
  if (!has_ridges) {
    message("Skipping ridgeline plots: ggridges not installed.")
    return(invisible(NULL))
  }
  library(ggridges)

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
      # Extra headroom above the top ridge so it is not clipped.
      scale_y_discrete(expand = expansion(add = c(0.2, 1.6))) +
      coord_cartesian(clip = "off") +
      theme_minimal() +
      theme(
        axis.text = element_text(size = 9),
        panel.grid.minor = element_blank()
      )

    save_plot(p_nssp, "fig2_ridgeline_nssp_seasons", width = 6, height = 4)
  }
}


# =============================================================================
# SUPPLEMENTARY: State-level time series
# =============================================================================


# Figure 3: protection advantage of each broadened window (September-
# March, October-April, year-round) over the October-March baseline, shown as a
# dot-and-whisker forest across stress-test scenarios (median and IQR).
plot_infant_ppx_window_advantage_forest <- function(stress_summary) {
  if (is.null(stress_summary) || nrow(stress_summary) == 0) return(invisible(NULL))
  window_levels <- c("September-March", "October-April", "Year-round")
  agg <- stress_summary |>
    filter(datasource == "nssp", window_name != "baseline_oct_mar") |>
    transmute(
      scenario_id,
      scenario_order,
      window = recode(
        window_name,
        early_sep_mar = "September-March",
        late_oct_apr = "October-April",
        year_round = "Year-round"
      ),
      med = 100 * delta_vs_baseline_oct_mar,
      lo = 100 * q25_delta_vs_baseline_oct_mar,
      hi = 100 * q75_delta_vs_baseline_oct_mar
    ) |>
    arrange(scenario_order)
  if (nrow(agg) == 0) return(invisible(NULL))

  labels_map <- c(
    reference_12mo = "Primary", censor_8mo = "8-mo censor",
    catchup_no_routine_visit = "Catch-up if no routine visit",
    uptake_50 = "Uptake 50%", uptake_75 = "Uptake 75%", uptake_100 = "Uptake 100%",
    newborn_first_week_20 = "First-week 20%", newborn_first_week_60 = "First-week 60%",
    visit_delay_0 = "No visit delay", visit_delay_30 = "30-day visit delay",
    waning_rapid = "Rapid waning"
  )
  lab_for <- function(id) { l <- unname(labels_map[id]); ifelse(is.na(l), id, l) }
  ordered_ids  <- unique(agg$scenario_id)            # already in scenario_order
  level_labels <- vapply(ordered_ids, lab_for, character(1))

  present_windows <- window_levels[window_levels %in% unique(agg$window)]
  agg$window <- factor(agg$window, levels = present_windows)
  # Manual vertical offset so the windows do not overlap within a scenario.
  n_w <- length(present_windows)
  offsets <- if (n_w > 1) seq(-0.24, 0.24, length.out = n_w) else 0
  names(offsets) <- present_windows
  agg$ypos <- match(agg$scenario_id, ordered_ids) + offsets[as.character(agg$window)]

  win_colors <- c("September-March" = "#1b6ca8",
                  "October-April"   = "#9aa0a6",
                  "Year-round"      = "#e08a3c")

  # Directional cues flanking the x = 0 line, placed below the tick labels and
  # above the axis title. y = -Inf anchors to the bottom panel edge (robust to the
  # reversed y-scale); vjust pushes the text down into the bottom margin, and
  # clip = "off" lets it render outside the panel. Small x offsets (data units)
  # keep each label on its side of the zero line.
  x_pad <- 1.5
  # Symmetric x-limits about 0 (span the widest whisker on either side).
  x_max <- max(abs(c(agg$lo, agg$hi)), na.rm = TRUE) * 1.05
  p <- ggplot(agg, aes(x = med, y = ypos, color = window)) +
    geom_vline(xintercept = 0, color = "grey60") +
    geom_errorbar(
      aes(xmin = lo, xmax = hi), orientation = "y", width = 0,
      show.legend = FALSE
    ) +
    geom_point(size = 1.5) +
    scale_y_reverse(breaks = seq_along(ordered_ids), labels = level_labels) +
    scale_color_manual(values = win_colors, breaks = present_windows) +
    coord_cartesian(clip = "off", xlim = c(-x_max, x_max)) +
    annotate("text", x = -x_pad, y = -Inf, hjust = 1, vjust = 59,
             label = "<- worse protection than baseline",
             size = 3.2, fontface = "italic", color = "grey35") +
    annotate("text", x = x_pad, y = -Inf, hjust = 0, vjust = 59,
             label = "better protection than baseline ->",
             size = 3.2, fontface = "italic", color = "grey35") +
    labs(x = "Difference from October-March baseline (percentage points)",
         y = NULL, color = NULL) +
    theme_minimal(base_size = 13) +
    theme(
      panel.grid.minor = element_blank(),
      # Float the legend at the top-right of the panel so it can be moved down
      # freely by lowering the y in legend.position (panel coords: 1 = top,
      # 0 = bottom) without adding any top margin/whitespace.
      legend.position = c(0.995, 1.08),
      legend.justification = c(1, 1),
      legend.direction = "horizontal",
      axis.title.x = element_text(vjust = -4),
      plot.margin = margin(t = 20, r = 14, b = 26, l = 5)
    )

  save_plot(p, "fig3_infant_ppx_early_start_advantage_forest", width = 8, height = 6)
  invisible(p)
}

# Figure 4: per-state distribution of expected hospitalizations averted vs the
# October-March baseline, by season, for three windows (September-March,
# October-April, year-round) shown as grouped violins (50% uptake).
plot_infant_hospitalizations_averted <- function(values, figure_stub) {
  win_colors <- c("September-March" = "#1b6ca8",
                  "October-April"   = "#9aa0a6",
                  "Year-round"      = "#e08a3c")

  if (is.null(values) || nrow(values) == 0) return(invisible(NULL))
  values_df <- values |>
    filter(datasource == "nssp", scenario_id == "uptake_50", !is.na(season),
           !is.na(hospitalizations_averted_vs_baseline)) |>
    transmute(
      season,
      hosp = hospitalizations_averted_vs_baseline,
      window = recode(
        comparison_window_name,
        early_sep_mar = "September-March",
        late_oct_apr = "October-April",
        year_round = "Year-round"
      )
    )
  if (is.null(values_df) || nrow(values_df) == 0) return(invisible(NULL))

  win_levels <- c("September-March", "October-April", "Year-round")
  values_df <- values_df |>
    mutate(season = factor(season, levels = sort(unique(season))),
           window = factor(window, levels = win_levels))

  summary_points <- values_df |>
    group_by(season, window) |>
    summarise(point = median(hosp, na.rm = TRUE),
              q25 = quantile(hosp, 0.25, na.rm = TRUE),
              q75 = quantile(hosp, 0.75, na.rm = TRUE),
              .groups = "drop")

  y_upper <- ceiling(max(values_df$hosp, na.rm = TRUE) / 5) * 5
  y_lower <- min(-50, floor(min(values_df$hosp, na.rm = TRUE) / 5) * 5)
  dodge <- position_dodge(width = 0.8)

  p <- ggplot(values_df, aes(x = season, y = hosp, fill = window)) +
    geom_violin(position = dodge, width = 0.7, alpha = 0.5, color = NA,
                scale = "width", trim = FALSE) +
    geom_errorbar(data = summary_points,
                  aes(x = season, ymin = q25, ymax = q75, group = window),
                  inherit.aes = FALSE, position = dodge, width = 0.2,
                  color = "black", linewidth = 0.4) +
    geom_point(data = summary_points, aes(x = season, y = point, group = window),
               inherit.aes = FALSE, position = dodge,
               color = "black", fill = "white", shape = 21, size = 2) +
    scale_fill_manual(values = win_colors, breaks = win_levels) +
    scale_y_continuous(breaks = scales::pretty_breaks(n = 6),
                       expand = expansion(mult = c(0.02, 0.06))) +
    coord_cartesian(ylim = c(y_lower, y_upper)) +
    labs(x = NULL, fill = NULL,
         y = "Expected RSV hospitalizations averted per state\n(50% uptake)") +
    theme_minimal(base_size = 11) +
    theme(panel.grid.major.x = element_blank(),
          panel.grid.minor = element_blank(),
          legend.position = "top", legend.justification = "right")

  save_plot(p, figure_stub, width = 8, height = 5)
  invisible(p)
}

# Figure 5: national hospitalizations averted vs the October-March baseline for
# three windows (September-March, October-April, year-round), by season, as
# stacked panels A (primary model) and B (50% uptake). Combined with cowplot.
plot_infant_hospitalizations_averted_ab <- function(summary_df) {
  if (!requireNamespace("cowplot", quietly = TRUE)) {
    message("Skipping figure 5: cowplot not installed.")
    return(invisible(NULL))
  }
  win_colors <- c("September-March" = "#1b6ca8",
                  "October-April"   = "#9aa0a6",
                  "Year-round"      = "#e08a3c")

  averted_panel <- function(scenario, y_title) {
    d <- summary_df |>
      filter(datasource == "nssp", scenario_id == scenario, !is.na(season)) |>
      transmute(
        season,
        hosp = total_hospitalizations_averted_vs_baseline,
        window = recode(
          comparison_window_name,
          early_sep_mar = "September-March",
          late_oct_apr = "October-April",
          year_round = "Year-round"
        )
      )
    if (is.null(d) || nrow(d) == 0) return(NULL)
    win_levels <- c("September-March", "October-April", "Year-round")
    d <- d |>
      mutate(season = factor(season, levels = sort(unique(season))),
             window = factor(window, levels = win_levels))

    ggplot(d, aes(x = season, y = hosp, fill = window)) +
      geom_col(position = position_dodge(0.75), width = 0.66) +
      geom_text(aes(y = pmax(hosp, 0),
                    label = formatC(as.integer(round(hosp)), format = "d", big.mark = ",")),
                position = position_dodge(0.75), vjust = -0.4, size = 3) +
      scale_fill_manual(values = win_colors, breaks = win_levels) +
      scale_y_continuous(expand = expansion(mult = c(0.05, 0.16))) +
      labs(x = NULL, y = y_title, fill = NULL) +
      theme_minimal(base_size = 12) +
      theme(panel.grid.minor = element_blank(),
            panel.grid.major.x = element_blank())
  }

  p_a <- averted_panel("reference_12mo", "National hospitalizations averted\n(primary 18.5% uptake)")
  p_b <- averted_panel("uptake_50", "National hospitalizations averted\n(50% uptake)")
  if (is.null(p_a) || is.null(p_b)) return(invisible(NULL))

  # Legend on panel A (top-right), so it sits just above the plot rather than
  # floating in a separate row; panel B drops the duplicate.
  p_a <- p_a + theme(legend.position = "top", legend.justification = "right")
  p_b <- p_b + theme(legend.position = "none")
  p <- cowplot::plot_grid(
    p_a, p_b, ncol = 1, labels = c("A", "B"), label_fontface = "bold",
    rel_heights = c(1.12, 1)
  )

  save_plot(p, "fig5_infant_ppx_hospitalizations_averted_primary_vs_50pct_uptake",
            width = 7.5, height = 8)
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
# MAIN
# =============================================================================

nssp_outside   <- read_table("nssp_outside_fraction_by_state")
nhsn_outside   <- read_table("nhsn_outside_fraction_by_state")
nssp_processed <- read_processed("nssp")
nhsn_processed <- read_processed("nhsn")
infant_stress  <- read_table("infant_ppx_stress_test_window_summary")
hosp_averted   <- read_table("infant_ppx_hospitalizations_averted")
hosp_summary   <- read_table("infant_ppx_hospitalizations_averted_summary")

# Start from a clean figure directory so no stale outputs remain.
unlink(list.files(fig_dir, pattern = "\\.(png|pdf)$", full.names = TRUE))

# Figure 1: choropleth grid of out-of-window RSV fraction
plot_choropleth_grid(nssp_outside, nhsn_outside, nssp_frac_lbl, nhsn_frac_lbl)

# Figure 2: ridgeline densities by season and age group
plot_ridgeline_nssp(nssp_outside)

# Figure 3: window advantage (Sep-Mar, Oct-Apr, year-round) over Oct-March baseline
plot_infant_ppx_window_advantage_forest(infant_stress)

# Figure 4: per-state distribution of hospitalizations averted, three windows, 50% uptake
plot_infant_hospitalizations_averted(
  hosp_averted,
  "fig4_infant_ppx_hospitalizations_averted_by_window"
)

# Figure 5: national hospitalizations averted, three windows, primary vs 50% uptake (panels A/B)
plot_infant_hospitalizations_averted_ab(hosp_summary)

# Supplementary: state-level time series
plot_timeseries(nssp_processed, nssp_ts_label, "nssp_",
                default_or(config$primary_outcome, "rsv_pct"), free_y = FALSE)
plot_timeseries(nhsn_processed, nhsn_ts_label, "nhsn_",
                default_or(config$nhsn_primary_outcome, "rsv_ped_0_4"), free_y = TRUE)

message("Figures saved to ", fig_dir)

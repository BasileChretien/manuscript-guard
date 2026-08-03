#' Find the project root
#'
#' Walks upwards looking for paper.yaml, the way git looks for .git.
#'
#' @param start Directory to start from. Defaults to the working directory.
#' @return Absolute path to the project root.
#' @export
mg_find_root <- function(start = getwd()) {
  current <- normalizePath(start, winslash = "/", mustWork = TRUE)
  repeat {
    if (file.exists(file.path(current, "paper.yaml"))) {
      return(current)
    }
    parent <- dirname(current)
    if (identical(parent, current)) {
      stop("no paper.yaml found in ", start, " or any parent directory", call. = FALSE)
    }
    current <- parent
  }
}

#' Check that an explicit display is a rendering of its own value
#'
#' Mirrors `_check_display_matches` in the Python emitter, and must keep mirroring it: the
#' results fragment is a cross-language contract, and a rule enforced on one side only is a
#' rule an author can step around by switching language.
#'
#' Nothing used to compare the two, so one call could publish a fabricated estimate and a
#' fabricated interval at once. Only numbers are checked; a string value is its own display,
#' and a label such as "2015-2024" is a value rather than a rounding of one.
#' @noRd
mg_check_display <- function(key, value, display) {
  if (is.logical(value) || !is.numeric(value)) {
    return(invisible(NULL))
  }
  # digits, optional decimals, optional exponent, optional unit carrying no digits of its
  # own. Without that last condition "(95% CI 2.10 to 7.02)" parses as the unit of 3.84.
  pattern <- paste0(
    "^\\s*([-+−]?)((?:\\d{1,3}(?:[,   ]\\d{3})+(?:\\.\\d+)?)|(?:\\d+(?:\\.\\d+)?))",
    "(?:[eE]([-+]?\\d+))?\\s*(%|[^\\s\\d][^\\d]*?)?\\s*$"
  )
  parts <- regmatches(display, regexec(pattern, display, perl = TRUE))[[1]]
  if (length(parts) == 0) {
    stop(
      key, ": display '", display, "' is not a rendering of ", format(value),
      ". A display carries one number, optionally with a unit - an interval or a sentence ",
      "belongs in separate keys, so each part can be quoted and checked on its own",
      call. = FALSE
    )
  }

  text <- gsub("[,   ]", "", parts[3])
  if (identical(parts[2], "-") || identical(parts[2], "−")) {
    text <- paste0("-", text)
  }
  if (nzchar(parts[4])) {
    text <- paste0(text, "e", parts[4])
  }

  shown <- as.numeric(text)
  decimals <- if (grepl("\\.", text)) nchar(sub("^[^.]*\\.", "", sub("e.*$", "", text))) else 0
  tolerance <- 0.5 * (10^-decimals) + abs(value) * 1e-9
  if (abs(shown - value) > tolerance) {
    stop(
      key, ": display '", display, "' reads as ", format(shown), ", but the value is ",
      format(value), ". Round it with `digits` rather than writing the number twice; if the ",
      "display is in different units, emit the value in those units and name them with `unit`",
      call. = FALSE
    )
  }
  invisible(NULL)
}

#' Display string for a value
#'
#' Mirrors the Python emitter exactly, with one concession to R: a double holding a whole
#' number is treated as a count, because R has no integer literal that survives ordinary
#' arithmetic. A quantity that really is 3.0 and should read "3.00" therefore needs an
#' explicit `digits`.
#' @noRd
mg_display <- function(key, value, display, digits) {
  if (!is.null(display)) {
    display <- as.character(display)
    mg_check_display(key, value, display)
    return(display)
  }
  if (is.logical(value)) {
    return(if (isTRUE(value)) "TRUE" else "FALSE")
  }
  if (is.character(value)) {
    return(value)
  }
  if (is.numeric(value)) {
    if (!is.null(digits)) {
      return(sprintf(paste0("%.", as.integer(digits), "f"), value))
    }
    if (is.integer(value) || (is.finite(value) && value == round(value) && abs(value) < 1e15)) {
      return(format(value, scientific = FALSE, trim = TRUE))
    }
    stop(
      key, ": a non-integer number needs `display` or `digits` so that every place it is ",
      "quoted rounds it identically",
      call. = FALSE
    )
  }
  stop(key, ": values of this type need an explicit `display`", call. = FALSE)
}

#' Write text with LF endings on every platform
#'
#' `writeLines(x, path)` opens a *text* connection, and on Windows a text connection
#' translates every newline to CRLF. `useBytes = TRUE` does not prevent it — that argument
#' is about encoding, not line endings. So the same analysis run on Windows and on Linux
#' produced byte-different results fragments, and since the guarantee here is a byte digest
#' over the file, a fragment written on one and checked out on the other reported
#' `results-edited` for a file nobody had touched. A binary connection writes what it is
#' given. This matches `newline="\n"` on every writer in the Python package.
#' @noRd
mg_write_lf <- function(text, path) {
  con <- file(path, open = "wb")
  on.exit(close(con), add = TRUE)
  writeLines(text, con, sep = "\n", useBytes = TRUE)
  invisible(path)
}

mg_git <- function(root, args) {
  out <- tryCatch(
    suppressWarnings(system2("git", c("-C", shQuote(root), args), stdout = TRUE, stderr = FALSE)),
    error = function(e) NULL
  )
  if (is.null(out) || length(out) == 0) NULL else trimws(paste(out, collapse = "\n"))
}

#' Create a results emitter
#'
#' The only supported way for an R analysis to publish a number.
#'
#' @param script Path to the analysis script. Inside a script, pass its own path.
#' @param inputs Character vector of data files read, project-relative or absolute.
#' @param root Project root. Detected from `script` when omitted.
#' @return A list of functions: `value()`, `add_input()`, `write()`.
#' @examples
#' \dontrun{
#' em <- mg_emitter("analysis/01_model.R", inputs = "data/reports.csv")
#' em$value("cohort.n_reports", 4000L)
#' em$value("ror.point", 3.4211, digits = 2)
#' em$write()
#' }
#' @export
mg_emitter <- function(script, inputs = character(), root = NULL) {
  script_path <- normalizePath(script, winslash = "/", mustWork = TRUE)
  project_root <- if (is.null(root)) mg_find_root(dirname(script_path)) else normalizePath(root, winslash = "/")
  state <- new.env(parent = emptyenv())
  state$values <- list()
  state$inputs <- as.character(inputs)

  relative <- function(path) {
    full <- normalizePath(path, winslash = "/", mustWork = TRUE)
    prefix <- paste0(project_root, "/")
    if (startsWith(full, prefix)) substring(full, nchar(prefix) + 1L) else full
  }

  value <- function(key, value, display = NULL, digits = NULL, unit = NULL,
                    quoted = TRUE, note = NULL) {
    if (!is.null(state$values[[key]])) {
      stop(key, " emitted twice by ", script_path, call. = FALSE)
    }
    shown <- mg_display(key, value, display, digits)
    entry <- list(value = value, display = shown)
    if (!is.null(digits)) entry$digits <- as.integer(digits)
    if (!is.null(unit)) entry$unit <- unit
    if (!isTRUE(quoted)) entry$quoted <- FALSE
    if (!is.null(note)) entry$note <- note
    state$values[[key]] <- entry
    invisible(NULL)
  }

  add_input <- function(path) {
    state$inputs <- c(state$inputs, path)
    invisible(NULL)
  }

  provenance <- function() {
    input_records <- lapply(state$inputs, function(path) {
      full <- if (file.exists(path)) path else file.path(project_root, path)
      if (!file.exists(full)) stop("declared input does not exist: ", full, call. = FALSE)
      list(
        path = relative(full),
        sha256 = digest::digest(file = full, algo = "sha256"),
        bytes = as.integer(file.info(full)$size)
      )
    })

    sha <- mg_git(project_root, c("rev-parse", "HEAD"))
    vcs <- list()
    if (!is.null(sha)) {
      vcs$sha <- sha
      vcs$dirty <- !is.null(mg_git(project_root, c("status", "--porcelain")))
      branch <- mg_git(project_root, c("rev-parse", "--abbrev-ref", "HEAD"))
      if (!is.null(branch)) vcs$branch <- branch
    }

    packages <- vapply(
      sessionInfo()$otherPkgs,
      function(p) as.character(p$Version),
      character(1)
    )

    session <- list(
      language = "R",
      version = paste(R.version$major, R.version$minor, sep = "."),
      platform = R.version$platform
    )
    # An empty R list serialises as [], and the schema asks for an object here. Omitting
    # the key is both valid and more honest than writing an empty container.
    if (length(packages) > 0) session$packages <- as.list(packages)

    # "+0900" is not RFC 3339; the offset needs its colon.
    stamp <- format(Sys.time(), "%Y-%m-%dT%H:%M:%S%z")
    stamp <- sub("([+-]\\d{2})(\\d{2})$", "\\1:\\2", stamp)

    provenance <- list(
      generated_by = relative(script_path),
      # Mirrors the Python emitter. G1 compares this rather than modification times,
      # because an mtime is set by `touch`.
      generated_by_sha256 = digest::digest(file = script_path, algo = "sha256"),
      generated_at = stamp,
      tool = list(name = "manuscriptguard", version = "0.1.0"),
      inputs = input_records,
      session = session
    )
    if (length(vcs) > 0) provenance$vcs <- vcs
    provenance
  }

  write <- function(path = NULL) {
    if (is.null(path)) {
      dir.create(file.path(project_root, "results"), showWarnings = FALSE, recursive = TRUE)
      stem <- sub("\\.[Rr]$|\\.[Rr]md$|\\.qmd$", "", basename(script_path))
      path <- file.path(project_root, "results", paste0(stem, ".json"))
    } else if (!grepl("^([A-Za-z]:)?[/\\\\]", path)) {
      path <- file.path(project_root, path)
    }
    dir.create(dirname(path), showWarnings = FALSE, recursive = TRUE)

    document <- list(
      schema = "manuscript-guard/results/1",
      provenance = provenance(),
      values = state$values
    )
    json <- jsonlite::toJSON(document, auto_unbox = TRUE, pretty = 2, digits = NA, null = "null")
    mg_write_lf(as.character(json), path)

    # The sidecar digest, byte-identical in intent to the Python emitter's: hash the file
    # you just wrote, so a later hand-edit cannot pass unnoticed.
    checksum <- digest::digest(file = path, algo = "sha256")
    mg_write_lf(paste0(checksum, "  ", basename(path)), paste0(path, ".sha256"))
    invisible(path)
  }

  list(value = value, add_input = add_input, write = write)
}

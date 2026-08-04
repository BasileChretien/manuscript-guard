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
  # The leading comparator is not decoration. "<0.001" is how a p-value too small to state
  # is written, and R rejected it while Python accepted it - so an analysis emitting a
  # rounded p-value was legal in one language and an error in the other, which is exactly
  # the divergence the docstring above warns about. Found by a cross-language test rather
  # than by reading: both emitters have to be exercised on the same input, or "mirrors" is
  # only a claim.
  pattern <- paste0(
    "^\\s*(<=|>=|<|>|\u2264|\u2265)?\\s*([-+\u2212]?)",
    "((?:\\d{1,3}(?:[,\u00a0\u202f ]\\d{3})+(?:\\.\\d+)?)|(?:\\d+(?:\\.\\d+)?))",
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

  text <- gsub("[,\u00a0\u202f ]", "", parts[4])
  if (identical(parts[3], "-") || identical(parts[3], "\u2212")) {
    text <- paste0("-", text)
  }
  if (nzchar(parts[5])) {
    text <- paste0(text, "e", parts[5])
  }

  shown <- as.numeric(text)

  if (nzchar(parts[2])) {
    # "<0.001" is true of any value below 0.001 and false of 0.4. Checking the direction
    # rather than the distance is the whole content of a comparator display.
    below <- parts[2] %in% c("<", "<=", "\u2264")
    satisfied <- if (below) value <= shown else value >= shown
    if (!satisfied) {
      stop(
        key, ": display '", display, "' says the value is ",
        if (below) "below " else "above ", format(shown), ", but it is ", format(value),
        call. = FALSE
      )
    }
    return(invisible(NULL))
  }

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

#' A cell that is a number written as text
#'
#' Mirrors `_NUMERIC_TEXT` in the Python emitter. This is the shape that used to slip
#' through there: `as.character()` accepted it, nothing compared it to anything, and a
#' hand-typed table number was indistinguishable from a computed one.
#' @noRd
mg_numeric_text <- function(text) {
  grepl("^\\s*[-+−]?[\\d,   ]*\\d(?:[.,]\\d+)?\\s*%?\\s*$", text, perl = TRUE) &&
    grepl("\\d", text)
}

#' Split a `{}` template into its literal pieces
#'
#' R has no `str.format`, so the same convention is implemented here rather than borrowing
#' a different one: a template written for one emitter has to mean the same in the other.
#' @noRd
mg_template_pieces <- function(template) {
  strsplit(template, "{}", fixed = TRUE)[[1]] -> pieces
  # strsplit drops a trailing empty piece; the count has to match the placeholders.
  wanted <- lengths(regmatches(template, gregexpr("{}", template, fixed = TRUE)))[[1]] + 1L
  length(pieces) <- wanted
  pieces[is.na(pieces)] <- ""
  pieces
}

#' A table cell composed from numbers
#'
#' `"77 (12.3)"` and `paste0(n, " (", pct, ")")` are the same string by the time `table()`
#' sees them, so no check can tell a computed cell from a typed one. The difference has to
#' be made at the API: hand over the numbers and a template, and the emitter formats them.
#'
#' Each part is a number, `list(number, digits)` when it needs rounding, or
#' `list(number, "<0.001")` when the number is not written as itself — the same three forms
#' the Python emitter takes, because a results fragment is a cross-language contract.
#'
#' @param template Text with `{}` where each number goes.
#' @param ... The numbers, in order.
#' @return An object `mg_table()` recognises as a composed cell.
#' @export
mg_cell <- function(template, ...) {
  parts <- list(...)
  pieces <- mg_template_pieces(template)
  if (length(pieces) != length(parts) + 1L) {
    stop(
      "cell template '", template, "' has ", length(pieces) - 1L, " placeholder(s) but ",
      length(parts), " value(s) were given",
      call. = FALSE
    )
  }
  structure(
    list(template = template, parts = parts, pieces = pieces),
    class = "mg_composed"
  )
}

#' Text the emitter itself assembled from structured data
#'
#' Mirrors `Verbatim` in the Python emitter: the one thing a cell can be that is neither a
#' number nor prose from the script. `code_list()` builds these by joining a list of codes it
#' was handed, so the cell is emitter output and carries the same exemption as a composed
#' cell. Not exported, which is what stops it becoming a way to type anything into a table.
#' @noRd
mg_verbatim <- function(text) structure(list(text = text), class = "mg_verbatim")

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
#' @return A list of functions: `value()`, `cell()`, `table()`, `code_list()`,
#'   `add_input()`, `write()`.
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
  state$tables <- list()
  state$code_lists <- list()
  # Which cells this emitter produced from numbers, per table, in the shape the fragment
  # publishes. G2 reads it and applies the same rule to a fragment from either language;
  # without it, a composed cell and a typed one are the same characters on disk.
  state$composed <- list()

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

  # Column headers are recorded with no `row`, matching the fragment schema and the Python
  # emitter's internal keying.
  HEADER <- -2L

  format_cell <- function(key, row, column, cell, digits) {
    where <- paste0("table '", key, "' row ", row, " column ", column)
    record <- function(literal, parts) {
      entry <- list(column = as.integer(column), literal = literal)
      if (!identical(row, HEADER)) entry$row <- as.integer(row)
      if (length(parts) > 0) entry$parts <- as.list(as.character(parts))
      state$composed[[key]] <- c(state$composed[[key]], list(entry))
    }

    if (inherits(cell, "mg_composed")) {
      shown <- vapply(
        seq_along(cell$parts),
        function(i) {
          part <- cell$parts[[i]]
          if (is.list(part)) {
            second <- part[[2]]
            if (is.character(second)) {
              mg_display(where, part[[1]], second, NULL)
            } else {
              mg_display(where, part[[1]], NULL, second)
            }
          } else {
            mg_display(where, part, NULL, NULL)
          }
        },
        character(1)
      )
      text <- paste0(cell$pieces, c(shown, ""), collapse = "")
      # The literal is the template with its placeholders removed: the part the script
      # typed, checked like any other text. Without it, "{} (n = 412)" would smuggle a
      # count into the table under the exemption the composed cell carries.
      record(paste0(cell$pieces, collapse = " "), shown)
      return(text)
    }
    if (inherits(cell, "mg_verbatim")) {
      record("", character())
      return(cell$text)
    }
    if (is.logical(cell)) {
      return(if (isTRUE(cell)) "TRUE" else "FALSE")
    }
    if (is.numeric(cell)) {
      wanted <- if (is.list(digits)) digits[[as.character(column)]] else digits
      shown <- mg_display(where, cell, NULL, wanted)
      # Recorded like a composed cell, because that is what it is: a number the emitter
      # formatted. Only the emitter knows that, so without the record a plain numeric cell
      # is indistinguishable from a typed one the moment anyone reads the file.
      record("", shown)
      return(shown)
    }
    if (is.character(cell)) {
      if (mg_numeric_text(cell)) {
        stop(
          where, ": '", cell, "' is a number written as text. Pass the number itself so it ",
          "is formatted here and traceable to this analysis; a numeric string is typed by ",
          "hand and compared to nothing",
          call. = FALSE
        )
      }
      return(cell)
    }
    stop(where, ": cells must be numbers or text", call. = FALSE)
  }

  #' Record a table. Cells are formatted here rather than in the manuscript.
  table_ <- function(key, columns, rows, caption = NULL, align = NULL,
                     quoted = TRUE, digits = NULL) {
    if (!is.null(state$tables[[key]])) {
      stop("table '", key, "' emitted twice by ", script_path, call. = FALSE)
    }
    width <- length(columns)
    for (i in seq_along(rows)) {
      if (length(rows[[i]]) != width) {
        stop(
          "table '", key, "': row ", i - 1L, " has ", length(rows[[i]]),
          " cells, header has ", width,
          call. = FALSE
        )
      }
    }

    header <- vapply(
      seq_along(columns),
      function(c) format_cell(key, HEADER, c - 1L, columns[[c]], NULL),
      character(1)
    )
    body <- lapply(seq_along(rows), function(r) {
      as.list(vapply(
        seq_along(rows[[r]]),
        function(c) format_cell(key, r - 1L, c - 1L, rows[[r]][[c]], digits),
        character(1)
      ))
    })

    spec <- list(columns = as.list(header), rows = body)
    if (!is.null(caption)) spec$caption <- caption
    if (!is.null(align)) {
      if (length(align) != width) {
        stop("table '", key, "': align has ", length(align), " entries, need ", width,
             call. = FALSE)
      }
      spec$align <- as.list(as.character(align))
    }
    if (!isTRUE(quoted)) spec$quoted <- FALSE
    state$tables[[key]] <- spec
    invisible(NULL)
  }

  #' The table of codes RECORD 6.1 asks for, built from the lists the analysis used.
  code_list <- function(key, entries, caption = NULL,
                        columns = c("Concept", "Coding system", "Codes")) {
    rows <- vector("list", length(entries))
    structured <- vector("list", length(entries))
    for (i in seq_along(entries)) {
      entry <- entries[[i]]
      missing <- setdiff(c("concept", "system", "codes"), names(entry))
      if (length(missing) > 0) {
        stop("code list '", key, "' entry ", i - 1L, ": missing ",
             paste(sort(missing), collapse = ", "), call. = FALSE)
      }
      codes <- as.character(entry$codes)
      if (length(codes) == 0) {
        stop(
          "code list '", key, "' entry ", i - 1L, ": no codes. An empty list published as a ",
          "definition says the concept matched nothing, which is a finding, not a ",
          "formatting choice",
          call. = FALSE
        )
      }
      # Joined here rather than by the caller, which is what makes the cell emitter output
      # rather than the script's prose - the same bargain as a composed cell.
      rows[[i]] <- list(
        as.character(entry$concept),
        as.character(entry$system),
        mg_verbatim(paste(codes, collapse = ", "))
      )
      structured[[i]] <- list(
        concept = as.character(entry$concept),
        system = as.character(entry$system),
        codes = as.list(codes)
      )
    }
    table_(key, as.character(columns), rows, caption = caption)
    state$code_lists[[key]] <- structured
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
    if (length(state$tables) > 0) {
      document$tables <- lapply(names(state$tables), function(key) {
        spec <- state$tables[[key]]
        entries <- state$composed[[key]]
        if (length(entries) > 0) spec$composed <- entries
        spec
      })
      names(document$tables) <- names(state$tables)
    }
    if (length(state$code_lists) > 0) document$code_lists <- state$code_lists
    json <- jsonlite::toJSON(document, auto_unbox = TRUE, pretty = 2, digits = NA, null = "null")
    mg_write_lf(as.character(json), path)

    # The sidecar digest, byte-identical in intent to the Python emitter's: hash the file
    # you just wrote, so a later hand-edit cannot pass unnoticed.
    checksum <- digest::digest(file = path, algo = "sha256")
    mg_write_lf(paste0(checksum, "  ", basename(path)), paste0(path, ".sha256"))
    invisible(path)
  }

  list(
    value = value,
    cell = mg_cell,
    table = table_,
    code_list = code_list,
    add_input = add_input,
    write = write
  )
}

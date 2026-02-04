/**
 * browser.js — Minimal helper JS for Ontology Dashboard.
 *
 * PRD-39, Task 2.7
 *
 * Provides lightweight UI enhancements on top of HTMX:
 *   - Loading indicator during HTMX requests
 *   - Copy-to-clipboard for instance URIs
 *   - Active nav-link highlighting
 */

/* global htmx */

"use strict";

// ---------------------------------------------------------------------------
// HTMX loading indicator
// ---------------------------------------------------------------------------

document.addEventListener("htmx:beforeRequest", function () {
    document.body.classList.add("htmx-loading");
});

document.addEventListener("htmx:afterRequest", function () {
    document.body.classList.remove("htmx-loading");
});

// ---------------------------------------------------------------------------
// Copy URI to clipboard
// ---------------------------------------------------------------------------

/**
 * Attach click-to-copy behaviour to elements with [data-copy-uri].
 * The attribute value is the text to copy.
 */
function initCopyButtons() {
    document.querySelectorAll("[data-copy-uri]").forEach(function (el) {
        el.addEventListener("click", function () {
            var uri = el.getAttribute("data-copy-uri");
            if (!uri) return;

            navigator.clipboard.writeText(uri).then(function () {
                var original = el.textContent;
                el.textContent = "Copied!";
                setTimeout(function () {
                    el.textContent = original;
                }, 1500);
            });
        });
    });
}

// ---------------------------------------------------------------------------
// Active nav-link highlighting
// ---------------------------------------------------------------------------

function highlightActiveNav() {
    var path = window.location.pathname;
    document.querySelectorAll(".nav-links a").forEach(function (link) {
        var href = link.getAttribute("href");
        if (href === path || (href !== "/" && path.startsWith(href))) {
            link.classList.add("active");
        } else {
            link.classList.remove("active");
        }
    });
}

// ---------------------------------------------------------------------------
// Initialise on DOM ready
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", function () {
    highlightActiveNav();
    initCopyButtons();
});

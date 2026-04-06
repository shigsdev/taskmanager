/**
 * Swipe gestures for mobile task cards.
 *
 * On touch devices, swiping a task card to the left reveals action buttons
 * (move to tier, delete). Tapping anywhere else resets the swipe.
 *
 * How it works:
 * 1. touchstart  — records where the finger landed (startX)
 * 2. touchmove   — tracks horizontal movement; if the user drags left
 *                   far enough, the card slides to reveal hidden buttons
 * 3. touchend    — if the swipe crossed a threshold (60px), lock the card
 *                   in the "swiped" position; otherwise, snap it back
 *
 * The CSS class .swiped (defined in style.css) applies
 * transform: translateX(-120px) to slide the card left and expose the
 * .swipe-actions container sitting just off the right edge.
 */

(function () {
    "use strict";

    const SWIPE_THRESHOLD = 60;  // minimum px to count as a swipe
    const SWIPE_OFFSET = 120;    // how far the card slides (matches CSS)

    let activeCard = null;       // the currently swiped-open card (if any)

    /**
     * Reset a card back to its default (un-swiped) position.
     */
    function resetCard(card) {
        if (!card) return;
        card.style.transform = "";
        card.classList.remove("swiped");
        if (card === activeCard) activeCard = null;
    }

    /**
     * Reset whatever card is currently swiped open.
     * Called when the user taps outside a swiped card.
     */
    function resetActiveCard() {
        if (activeCard) resetCard(activeCard);
    }

    /**
     * Attach touch listeners to a single task card element.
     * Called for every card rendered on the board.
     */
    function bindSwipe(card) {
        let startX = 0;
        let startY = 0;
        let currentX = 0;
        let swiping = false;

        card.addEventListener("touchstart", function (e) {
            // If another card is open, close it first
            if (activeCard && activeCard !== card) resetActiveCard();

            const touch = e.touches[0];
            startX = touch.clientX;
            startY = touch.clientY;
            currentX = 0;
            swiping = false;
            // Remove transition during drag for smooth tracking
            card.style.transition = "none";
        }, { passive: true });

        card.addEventListener("touchmove", function (e) {
            const touch = e.touches[0];
            const dx = touch.clientX - startX;
            const dy = touch.clientY - startY;

            // If vertical movement is larger, user is scrolling — don't swipe
            if (!swiping && Math.abs(dy) > Math.abs(dx)) return;

            // Only allow left swipe (negative dx)
            if (dx < 0) {
                swiping = true;
                // Clamp: don't let them drag further than SWIPE_OFFSET
                currentX = Math.max(dx, -SWIPE_OFFSET);
                card.style.transform = "translateX(" + currentX + "px)";
            }
        }, { passive: true });

        card.addEventListener("touchend", function () {
            // Restore CSS transition for the snap animation
            card.style.transition = "";

            if (Math.abs(currentX) >= SWIPE_THRESHOLD) {
                // Lock in swiped position
                card.classList.add("swiped");
                card.style.transform = "translateX(-" + SWIPE_OFFSET + "px)";
                activeCard = card;
            } else {
                // Snap back
                resetCard(card);
            }
            swiping = false;
        }, { passive: true });
    }

    /**
     * Inject the swipe-action buttons into a task card.
     * These sit in a container that's hidden off the right edge until
     * the card is swiped left.
     */
    function addSwipeActions(card) {
        // Don't double-add
        if (card.querySelector(".swipe-actions")) return;

        const taskId = card.dataset.id;
        if (!taskId) return;

        const actions = document.createElement("div");
        actions.className = "swipe-actions";

        // "Move" button — opens the detail panel so the user can pick a tier
        const moveBtn = document.createElement("button");
        moveBtn.className = "swipe-action-move";
        moveBtn.textContent = "Move";
        moveBtn.addEventListener("click", function (e) {
            e.stopPropagation();
            resetCard(card);
            // Trigger the detail panel open by clicking the card body
            card.click();
        });
        actions.appendChild(moveBtn);

        // "Delete" button — soft-deletes the task
        const delBtn = document.createElement("button");
        delBtn.className = "swipe-action-delete";
        delBtn.textContent = "Delete";
        delBtn.addEventListener("click", function (e) {
            e.stopPropagation();
            resetCard(card);
            // Use the global taskDelete from app.js
            if (typeof taskDelete === "function") {
                taskDelete(taskId);
            }
        });
        actions.appendChild(delBtn);

        card.style.position = "relative";
        card.style.overflow = "hidden";
        card.appendChild(actions);
    }

    /**
     * Scan all .task-card elements and set up swipe if on a touch device.
     * Called after the board renders (via a MutationObserver or manual call).
     */
    function initSwipeCards() {
        // Only enable on touch-capable devices
        if (!("ontouchstart" in window)) return;

        document.querySelectorAll(".task-card").forEach(function (card) {
            if (card.dataset.swipeBound) return;  // already set up
            card.dataset.swipeBound = "1";
            addSwipeActions(card);
            bindSwipe(card);
        });
    }

    // Close swiped card when tapping outside
    document.addEventListener("touchstart", function (e) {
        if (activeCard && !activeCard.contains(e.target)) {
            resetActiveCard();
        }
    }, { passive: true });

    // Expose so app.js can call after rendering the board
    window.initSwipeCards = initSwipeCards;

    // Also watch for DOM changes (new cards added dynamically)
    // MutationObserver re-scans whenever children are added to tier bodies
    const observer = new MutationObserver(function () {
        initSwipeCards();
    });

    document.addEventListener("DOMContentLoaded", function () {
        const board = document.getElementById("tierBoard");
        if (board) {
            observer.observe(board, { childList: true, subtree: true });
        }
        initSwipeCards();
    });
})();

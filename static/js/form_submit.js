document.addEventListener('DOMContentLoaded', function () {

    document.addEventListener('submit', function (e) {
        const form = e.target;
        const submitBtn = form.querySelector('[type="submit"]');
        if (!submitBtn) return;

        const loadingText = submitBtn.dataset.loadingText || 'Cargando...';

        submitBtn.dataset.originalHtml = submitBtn.innerHTML;
        submitBtn.dataset.originalStyle = submitBtn.getAttribute('style') || '';
        submitBtn.disabled = true;
        submitBtn.style.opacity = '0.75';
        submitBtn.style.cursor = 'not-allowed';
        submitBtn.innerHTML = `
            <span class="relative z-10 flex items-center justify-center">
                <svg class="animate-spin w-5 h-5 mr-2" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
                </svg>
                ${loadingText}
            </span>
        `;
    });

    window.addEventListener('pageshow', function (e) {
        if (e.persisted) {
            document.querySelectorAll('[type="submit"]').forEach(function (btn) {
                btn.disabled = false;
                btn.style.opacity = '';
                btn.style.cursor = '';
                if (btn.dataset.originalHtml) btn.innerHTML = btn.dataset.originalHtml;
                if (btn.dataset.originalStyle !== undefined) btn.setAttribute('style', btn.dataset.originalStyle);
            });
        }
    });

});
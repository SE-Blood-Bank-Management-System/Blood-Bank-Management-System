"""Background STAT checks must not count as interactive session activity."""
from django.contrib.sessions.middleware import SessionMiddleware
from django.utils.cache import patch_vary_headers


class ActivitySessionMiddleware(SessionMiddleware):
    def process_response(self, request, response):
        match = getattr(request, 'resolver_match', None)
        session = getattr(request, 'session', None)
        passive = request.method == 'GET' and match and match.view_name == 'requisitions:stat_alerts'
        if passive and session is not None and not session.modified and not session.is_empty():
            # SessionStore.load still enforces server-side expiry. Avoid save/cookie
            # renewal for an unchanged poll, even with SESSION_SAVE_EVERY_REQUEST.
            if session.accessed:
                patch_vary_headers(response, ('Cookie',))
            return response
        # Includes expired/flushed sessions, whose stale cookie must be deleted.
        return super().process_response(request, response)

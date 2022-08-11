from django.shortcuts import redirect
from django.urls import resolve


def name_middleware(get_response):
    # One-time configuration and initialization.

    def middleware(request):
        current_url = resolve(request.path_info).url_name or ''
        if request.method == 'GET' and not 'planetrip' in current_url and not 'home' in current_url and not request.session.get('name'):
            request.session['redirected_from'] = request.path_info
            return redirect('home')

        response = get_response(request)

        # Code to be executed for each request/response after
        # the view is called.

        return response

    return middleware

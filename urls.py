"""tipr URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path, re_path

from tipr.views import *


urlpatterns = [ 
    path('planetrip/', include('planetrip.urls')),
    path('goop/', include('goop.urls')),        
    path('admin/', admin.site.urls),
    path('', Home.as_view(), name='home'),
    path('register/', Register.as_view(), name='register'),
    path('sit/', Sit.as_view(), name='sit'),
    path('submit/', Submit.as_view(), name='submit'),
    path('update_worker.js', Worker.as_view(), name='worker'),
    re_path('game/(?P<id>\d+)', GamePage.as_view(), name='game'),
]


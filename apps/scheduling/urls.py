from django.urls import path

from apps.scheduling import views

app_name = "scheduling"

urlpatterns = [
    path("", views.CalendarView.as_view(), name="calendar"),
    path("agenda/", views.agenda_partial, name="agenda_partial"),
    path("nou/", views.AppointmentCreateView.as_view(), name="create"),
    path("<int:pk>/", views.AppointmentDetailView.as_view(), name="detail"),
    path("<int:pk>/modifica/", views.AppointmentUpdateView.as_view(), name="update"),
    path("<int:pk>/sterge/", views.delete_appointment, name="delete"),
    path("<int:pk>/sincronizeaza/", views.push_to_calendar, name="push_external"),
    path("alarme/", views.ReminderListView.as_view(), name="reminder_list"),
    path("alarme/nou/", views.ReminderCreateView.as_view(), name="reminder_create"),
    path("alarme/<int:pk>/", views.ReminderDetailView.as_view(), name="reminder_detail"),
    path("alarme/<int:pk>/modifica/", views.ReminderUpdateView.as_view(), name="reminder_update"),
    path("alarme/<int:pk>/amana/", views.snooze_reminder, name="reminder_snooze"),
    path("alarme/<int:pk>/rezolva/", views.complete_reminder, name="reminder_complete"),
]

import os
from dotenv import load_dotenv

load_dotenv()

from flask import Flask
from flask import session
from flask import url_for
from flask import request
from flask import redirect
from flask import render_template
from flask import jsonify
from flask_cors import CORS, cross_origin

from authlib.integrations.flask_client import OAuth

from spotipy import Spotify
from spotipy.oauth2 import SpotifyOAuth
from spotipy.cache_handler import FlaskSessionCacheHandler

from ytmusicapi import YTMusic, OAuthCredentials

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')

SPOTIPY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
SPOTIPY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')
REDIRECT_URI = 'https://ytify-swart.vercel.app/callback/spotify'
scope = 'playlist-read-private'

AUTH_URL = 'https://accounts.spotify.com/authorize'
TOKEN_URL = 'https://accounts.spotify.com/api/token'
API_BASE_URL = 'https://api.spotify.com/v1/'

GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')
GOOGLE_REDIRECT_URI = 'https://ytify-swart.vercel.app/callback/google'

YOUTUBE_CLIENT_ID = os.getenv('YOUTUBE_CLIENT_ID')
YOUTUBE_CLIENT_SECRET = os.getenv('YOUTUBE_CLIENT_SECRET')

cache_handler = FlaskSessionCacheHandler(session)
sp_oauth = SpotifyOAuth(
    client_id=SPOTIPY_CLIENT_ID,
    client_secret = SPOTIPY_CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    scope=scope,
    cache_handler=cache_handler,
    show_dialog=True
)

sp = Spotify(auth_manager=sp_oauth)

# oAuth Setup
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    access_token_url='https://accounts.google.com/o/oauth2/token',
    access_token_params=None,
    authorize_url='https://accounts.google.com/o/oauth2/auth',
    authorize_params={'access_type': 'offline', 'prompt': 'consent'},
    api_base_url='https://www.googleapis.com/oauth2/v1/',
    userinfo_endpoint='https://openidconnect.googleapis.com/v1/userinfo',  # This is only needed if using openId to fetch user info
    client_kwargs={'scope': 'email profile https://www.googleapis.com/auth/youtube'},
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration'
)


@app.route('/')
def index():
    
    if sp_oauth.validate_token(cache_handler.get_cached_token()) and 'google_token' in session:
        return redirect(url_for('playlists'))
   
    sp = False
    yt = False

    if sp_oauth.validate_token(cache_handler.get_cached_token()):
        sp = True
    if 'google_token' in session:
        yt = True

    logged = {
        'spotify':sp,
        'youtube':yt
    }

    return render_template('index.html', logged=logged)

@app.route('/login', methods=['GET', 'OPTIONS'])
def login():
    if not sp_oauth.validate_token(cache_handler.get_cached_token()):
        auth_url = sp_oauth.get_authorize_url()
        return redirect(auth_url)
    return redirect(url_for('index')) 


@app.route('/google_login', methods=['GET', 'OPTIONS'])
def google_login():
    if 'google_token' in session:
        return redirect(url_for('playlists'))

    google = oauth.create_client('google')  # create the google oauth client
    redirect_uri = url_for('callback_google', _external=True)
    return google.authorize_redirect(redirect_uri)


@app.route('/callback/spotify')
def callback_spotify():
    sp_oauth.get_access_token(request.args['code'])
    return redirect(url_for('index'))


@app.route('/callback/google')
def callback_google():
    google = oauth.create_client('google') 

    token = google.authorize_access_token()

    resp = google.get('userinfo')  
    user_info = resp.json()
    user = oauth.google.userinfo()  

    session['google_token'] = token
    session['profile'] = user_info
    session.permanent = True  # make the session permanant so it keeps existing after broweser gets closed


    return redirect(url_for('index'))


def get_playlists():
    user_playlists = sp.current_user_playlists()
    return user_playlists['items']


@app.route('/playlists')
def playlists():
    if not sp_oauth.validate_token(cache_handler.get_cached_token()):
        return redirect(url_for('index'))

    user_playlists = get_playlists()

    return render_template('playlist_list.html', user_playlists=user_playlists)


def get_playlist(id):
    user_playlists = get_playlists()

    pl = user_playlists[int(id)]
    pl_id = pl['id']

    user = sp.current_user()['display_name']

    results = sp.user_playlist_tracks(user,pl_id)
    tracks = results['items']
    while results['next']:
        results = sp.next(results)
        tracks.extend(results['items'])
    
    pl_tracks = []
    for track in tracks:
        if track['track']:
            name = track['track']['name']
            album = track['track']['album']['name']
            artists = ", ".join([artist['name'] for artist in track['track']['artists']])

            track_info = {"name": name, "album": album, "artists":artists}
            pl_tracks.append(track_info)
    
    return pl, pl_tracks


@app.route('/playlists/<id>')
def playlist(id):
    if not sp_oauth.validate_token(cache_handler.get_cached_token()):
        return redirect(url_for('index'))

    pl, pl_tracks = get_playlist(id)

    context = {
        "playlist": pl, 
        "tracks": pl_tracks
    }
    
    return render_template('playlist.html', data = context)
    

@app.route('/create_playlist/<id>',methods=['GET', 'POST'])
def create_playlist(id):
    if not sp_oauth.validate_token(cache_handler.get_cached_token()):
        return redirect(url_for('index'))

    form = request.form
    songs = [int(val) for val in form]

    token = session['google_token']
    # Extract token details
    access_token = token.get('access_token')
    refresh_token = token.get('refresh_token')  # Only available if `access_type=offline`
    expires_in = token.get('expires_in')  # Time (seconds) until token expires
    expires_at = token.get('expires_at')  # Unix timestamp of expiration time

    ytoauth = {
        "scope": "https://www.googleapis.com/auth/youtube",
        "token_type": "Bearer",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
        "expires_in": expires_in
    }

    client_id = YOUTUBE_CLIENT_ID
    client_secret = YOUTUBE_CLIENT_SECRET

    ytmusic = YTMusic(ytoauth, oauth_credentials=OAuthCredentials(client_id=client_id, client_secret=client_secret))

    print(id)
    pl, pl_tracks = get_playlist(id)
    
    playlistId = ytmusic.create_playlist(pl['name'], pl['description'])

    song_ids = []
    for i, track in enumerate(pl_tracks):
        if i in songs:
            query = f"{track['name']} {track['artists']}"
            print(query)
            search_results = ytmusic.search(query)
            for result in search_results:
                if (result['resultType'] == 'song' or result['resultType'] == 'video') :
                    song_ids.append(result['videoId'])
                    break
            else:
                print("not found: ", track['name'])
    
    if song_ids:
        status = ytmusic.add_playlist_items(playlistId, song_ids, duplicates=True)
        link = f"//music.youtube.com/playlist?list={playlistId}"

    return link

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


@app.errorhandler(404)
def page_not_found(e):
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=False)

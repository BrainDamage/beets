# This file is part of beets.
# Copyright 2013, Adrian Sampson.
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.

"""A Web interface to beets."""
from beets.plugins import BeetsPlugin
from beets import ui
from beets import util
import beets.library
import flask
from flask import g
import os
import json


# Utilities.

def _rep(obj, expand=False):
    """Get a flat -- i.e., JSON-ish -- representation of a beets Item or
    Album object. For Albums, `expand` dictates whether tracks are
    included.
    """
    out = dict(obj)

    if isinstance(obj, beets.library.Item):
        del out['path']

        # Get the size (in bytes) of the backing file. This is useful
        # for the Tomahawk resolver API.
        try:
            out['size'] = os.path.getsize(util.syspath(obj.path))
        except OSError:
            out['size'] = 0

        return out

    elif isinstance(obj, beets.library.Album):
        del out['artpath']
        if expand:
            out['items'] = [_rep(item) for item in obj.items()]
        return out

def json_generator(items, root):
    """Generator that dumps list of beets Items or Albums as JSON

    :param root:  root key for JSON
    :param items: list of :class:`Item` or :class:`Album` to dump
    :returns:     generator that yields strings
    """
    yield '{"%s":[' % root
    first = True
    for item in items:
        if first:
            first = False
        else:
            yield ','
        yield json.dumps(_rep(item))
    yield ']}'

def _extract_ids(string_ids):
    """Parses ``string_ids`` as a comme separated list of integers and returns
    that list of integers.
    """
    ids = []
    for id in string_ids.split(','):
        try:
            ids.append(int(id))
        except ValueError:
            pass
    return ids

def resource(name):
    """Decorates a function to handle RESTful HTTP requests for a resource.
    """
    def make_responder(retriever):
        def responder(entity_ids):
            entity_ids = _extract_ids(entity_ids)
            entities = [retriever(id) for id in entity_ids]
            entities = [entity for entity in entities if entity]

            if len(entities) == 1:
                return flask.jsonify(_rep(entities[0]))
            elif entities:
                return app.response_class(
                        json_generator(entities, root=name),
                        mimetype='application/json')
            else:
                return flask.abort(404)
        responder.__name__ = 'get_%s' % name
        return responder
    return make_responder

def resource_query(name):
    """Decorates a function to handle RESTful HTTP queries for resources.
    """
    def make_responder(query_func):
        def responder(query):
            parts = query.split('/')
            entities = query_func(parts)
            return app.response_class(
                    json_generator(entities, root='results'),
                    mimetype='application/json')
        responder.__name__ = 'query_%s' % name
        return responder
    return make_responder

def resource_list(name):
    """Decorates a function to handle RESTful HTTP request for a list of
    resources.
    """
    def make_responder(list_all):
        def responder():
            return app.response_class(
                    json_generator(g.lib.items(), root=name),
                    mimetype='application/json')
        responder.__name__ = 'all_%s' % name
        return responder
    return make_responder


# Flask setup.

app = flask.Flask(__name__)

@app.before_request
def before_request():
    g.lib = app.config['lib']


# Items.

@app.route('/item/<entity_ids>')
@resource('items')
def get_item(id):
    return g.lib.get_item(id)


@app.route('/item/')
@app.route('/item/query/')
@resource_list('items')
def all_items():
    return g.lib.items()

@app.route('/item/<int:item_id>/file')
def item_file(item_id):
    item = g.lib.get_item(item_id)
    response = flask.send_file(item.path, as_attachment=True,
                               attachment_filename=os.path.basename(item.path))
    response.headers['Content-Length'] = os.path.getsize(item.path)
    return response

@app.route('/item/query/<path:query>')
@resource_query('items')
def item_query(queries):
    return g.lib.items(queries)


# Albums.

@app.route('/album/<entity_ids>')
@resource('albums')
def get_album(id):
    return g.lib.get_album(id)

@app.route('/album/')
@app.route('/album/query/')
@resource_list('albums')
def all_albums():
    return g.lib.albums()

@app.route('/album/query/<path:query>')
@resource_query('albums')
def album_query(queries):
    return g.lib.album(queries)

@app.route('/album/<int:album_id>/art')
def album_art(album_id):
    album = g.lib.get_album(album_id)
    return flask.send_file(album.artpath)


# Artists.

@app.route('/artist/')
def all_artists():
    with g.lib.transaction() as tx:
        rows = tx.query("SELECT DISTINCT albumartist FROM albums")
    all_artists = [row[0] for row in rows]
    return flask.jsonify(artist_names=all_artists)


# Library information.

@app.route('/stats')
def stats():
    with g.lib.transaction() as tx:
        item_rows = tx.query("SELECT COUNT(*) FROM items")
        album_rows = tx.query("SELECT COUNT(*) FROM albums")
    return flask.jsonify({
        'items': item_rows[0][0],
        'albums': album_rows[0][0],
    })


# UI.

@app.route('/')
def home():
    return flask.render_template('index.html')


# Plugin hook.

class WebPlugin(BeetsPlugin):
    def __init__(self):
        super(WebPlugin, self).__init__()
        self.config.add({
            'host': u'',
            'port': 8337,
        })

    def commands(self):
        cmd = ui.Subcommand('web', help='start a Web interface')
        cmd.parser.add_option('-d', '--debug', action='store_true',
                              default=False, help='debug mode')
        def func(lib, opts, args):
            args = ui.decargs(args)
            if args:
                self.config['host'] = args.pop(0)
            if args:
                self.config['port'] = int(args.pop(0))

            app.config['lib'] = lib
            app.run(host=self.config['host'].get(unicode),
                    port=self.config['port'].get(int),
                    debug=opts.debug, threaded=True)
        cmd.func = func
        return [cmd]
